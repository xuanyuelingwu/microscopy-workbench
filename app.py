"""Loopback-only local microscopy application, using the Python standard library."""
from __future__ import annotations
import argparse
import concurrent.futures
import io
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from PIL import Image
import core

BASE = Path(__file__).resolve().parent


class State:
    def __init__(self, root):
        self.root = root.resolve()
        self.uploads = self.root / "uploads"
        self.outputs = self.root / "outputs"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.datasets = {}
        self.jobs = {}
        self.lock = threading.Lock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.token = secrets.token_urlsafe(32)

    def register(self, path):
        ds = core.Dataset(path)
        try:
            info = ds.info()
        except Exception:
            ds.close()
            raise
        key = secrets.token_hex(12)
        with self.lock:
            self.datasets[key] = ds
        return {"id": key, "metadata": info, "source_path": str(ds.path)}

    def dataset(self, key):
        if key not in self.datasets:
            raise core.UserError("源文件会话不存在；服务重启后请重新选择文件。")
        return self.datasets[key]

    def submit(self, request):
        ds = self.dataset(request.get("dataset"))
        mode = request.get("mode")
        if mode not in {"volume", "video", "preview"}:
            raise core.UserError("未知任务类型。")
        config = request.get("config", {})
        config = json.loads(json.dumps(config))
        config["mode"] = "volume" if mode == "volume" else "video"
        if mode == "preview":
            channels = core.display_settings(ds, config)
            sel = ds.selection(config.get("selection"), variable="T")
            times, _ = ds.time_axis(sel, channels[0]["index"], config.get("time_interval_s"))
            config.update(start=0, end=len(times)-1, preview_only=True, roi=None,
                          roi_reference_frame=0)
        else:
            config.pop("preview_only", None)
        # Validate dimensions and LUT before enqueuing expensive work.
        core.display_settings(ds, config)
        if mode == "volume" and ds.sizes.get("Z", 1) < 2:
            raise core.UserError("此文件没有 Z 层扫维度。")
        if mode != "volume" and ds.sizes.get("T", 1) < 2:
            raise core.UserError("此文件没有 T 时间维度。")
        key = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4)
        folder = self.outputs / key
        job = {"id": key, "mode": mode, "status": "queued", "progress": 0,
               "message": "等待处理", "folder": str(folder), "created": time.time()}
        event = threading.Event()
        with self.lock:
            self.jobs[key] = {**job, "_event": event}

        def update(p, message):
            with self.lock:
                self.jobs[key].update(progress=p, message=message)

        def work():
            with self.lock:
                self.jobs[key].update(status="running", message="开始处理")
            try:
                progress = core.Progress(update, event)
                progress.check()
                fn = core.make_volume if mode == "volume" else core.make_video
                result = fn(ds, config, folder, progress)
                with self.lock:
                    self.jobs[key].update(status="done", progress=100, message="完成",
                                          result=result)
            except core.Cancelled as e:
                with self.lock:
                    self.jobs[key].update(status="cancelled", message=str(e))
            except Exception as e:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
                with self.lock:
                    self.jobs[key].update(status="error", message=str(e),
                                          error_log="error.log")
        self.pool.submit(work)
        return self.job(key)

    def job(self, key):
        with self.lock:
            if key not in self.jobs:
                raise core.UserError("任务不存在。")
            return {k: v for k, v in self.jobs[key].items() if not k.startswith("_")}


class Handler(BaseHTTPRequestHandler):
    server_version = "MicroscopyWorkbench/1"
    protocol_version = "HTTP/1.1"

    @property
    def state(self):
        return self.server.state

    def log_message(self, fmt, *args):
        # Request tokens are never printed.
        path = urlsplit(self.path).path
        print(time.strftime("%H:%M:%S"), self.command, path, flush=True)

    def headers_safe(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "SAMEORIGIN")

    def send(self, data, status=200, content_type="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(core.plain(data), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.headers_safe()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, query):
        token = self.headers.get("X-Workbench-Token", "") or query.get("token", [""])[0]
        return secrets.compare_digest(token, self.state.token)

    def check_host(self):
        allowed = {"127.0.0.1", "localhost", "[::1]"}
        host = self.headers.get("Host", "").rsplit(":", 1)[0]
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin:
            u = urlsplit(origin)
            if u.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
            if u.port != self.server.server_address[1]:
                return False
        return True

    def read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n < 0 or n > 2_000_000:
            raise core.UserError("JSON 请求过大。")
        return json.loads(self.rfile.read(n))

    def do_GET(self):
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            self.send({"error": str(e)}, 400)

    def route_get(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if not self.check_host():
            self.send({"error": "只接受本机地址请求。"}, 403)
            return
        path = unquote(u.path)
        if path.startswith("/api/") or path.startswith("/outputs/"):
            if not self.authorized(q):
                self.send({"error": "本地会话令牌缺失；请从启动脚本重新打开页面。"}, 403)
                return
        if path == "/api/status":
            self.send({"version": core.VERSION, "data_root": str(self.state.root),
                       "jobs": [self.state.job(k) for k in list(self.state.jobs)]})
        elif path.startswith("/api/jobs/"):
            self.send(self.state.job(path.split("/")[-1]))
        elif path.startswith("/outputs/"):
            self.file(self.state.outputs, path[len("/outputs/"):])
        elif path in {"/", "/index.html"}:
            self.file(BASE / "static", "index.html")
        else:
            self.file(BASE / "static", path.lstrip("/"))

    def do_POST(self):
        try:
            self.route_post()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except core.UserError as e:
            self.send({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self.send({"error": str(e)}, 400)

    def route_post(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if not self.check_host() or not self.authorized(q):
            self.send({"error": "未授权的本地请求。"}, 403)
            return
        if u.path == "/api/upload":
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 200 * 1024**3:
                raise core.UserError("文件为空或超过 200 GB。")
            if shutil.disk_usage(self.state.root).free < n + 512*1024**2:
                raise core.UserError("本地缓存空间不足。可使用“本机路径”模式避免复制大文件。")
            filename = unquote(self.headers.get("X-Filename", "source.nd2"))
            # Discard path components sent by a browser / crafted request.
            filename = filename.replace("\\", "/").split("/")[-1]
            if Path(filename).suffix.lower() not in {".nd2", ".tif", ".tiff"}:
                raise core.UserError("请选择 ND2 或 TIFF 文件。")
            target = self.state.uploads / secrets.token_hex(8)
            target.mkdir()
            path = target / filename
            try:
                with path.open("wb") as f:
                    remaining = n
                    while remaining:
                        b = self.rfile.read(min(8*1024**2, remaining))
                        if not b:
                            raise core.UserError("文件上传中断。")
                        f.write(b)
                        remaining -= len(b)
                self.send(self.state.register(path))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return
        req = self.read_json()
        if u.path == "/api/open-path":
            path = req.get("path", "").strip().strip('"')
            self.send(self.state.register(path))
        elif u.path == "/api/frame":
            ds = self.state.dataset(req.get("dataset"))
            cfg = req.get("config", {})
            channels = core.display_settings(ds, cfg)
            selection = ds.selection(cfg.get("selection"))
            a = ds.frame(selection)
            im = Image.fromarray(core.render_rgb(a, channels))
            # The interactive canvas always receives native XY dimensions.
            b = io.BytesIO()
            im.save(b, format="PNG")
            self.send(b.getvalue(), content_type="image/png")
        elif u.path == "/api/axes":
            ds = self.state.dataset(req.get("dataset"))
            cfg = req.get("config", {})
            channels = core.display_settings(ds, cfg)
            out = {}
            if ds.sizes.get("T", 1) > 1:
                times, src = ds.time_axis(ds.selection(cfg.get("selection"), variable="T"),
                                         channels[0]["index"], cfg.get("time_interval_s"))
                out.update(times_s=times.tolist(), time_source=src)
            if ds.sizes.get("Z", 1) > 1:
                z, order, src, _, warnings = ds.z_axis(
                    ds.selection(cfg.get("selection"), variable="Z"), channels[0]["index"],
                    cfg.get("z_mode", "auto"), cfg.get("calibration"))
                out.update(z_um=z.tolist(), z_order=order.tolist(), z_source=src, warnings=warnings)
            self.send(out)
        elif u.path == "/api/jobs":
            self.send(self.state.submit(req), status=202)
        elif u.path == "/api/cancel":
            key = req.get("id")
            self.state.job(key)
            self.state.jobs[key]["_event"].set()
            self.send({"ok": True})
        elif u.path == "/api/open-output":
            job = self.state.job(req.get("id"))
            folder = Path(job["folder"])
            if not folder.is_dir():
                raise core.UserError("输出目录尚未创建。")
            if os.name == "nt":
                os.startfile(folder)
            self.send({"path": str(folder)})
        else:
            self.send({"error": "接口不存在。"}, 404)

    def file(self, root, relative):
        root = root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            self.send({"error": "文件不存在。"}, 404)
            return
        size = path.stat().st_size
        start, end = 0, size-1
        rng = self.headers.get("Range")
        if rng:
            try:
                unit, val = rng.split("=")
                a, b = val.split("-")
                if unit != "bytes":
                    raise ValueError()
                if a:
                    start = int(a)
                    end = min(int(b), size-1) if b else size-1
                else:
                    start, end = max(0, size-int(b)), size-1
                if not 0 <= start <= end < size:
                    raise ValueError()
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */" + str(size))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if rng else 200)
        self.headers_safe()
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in {".html", ".js", ".css", ".txt"}:
            kind += "; charset=utf-8"
        self.send_header("Content-Type", kind)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end-start+1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end-start+1
            while remaining > 0:
                data = f.read(min(1024*1024, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)


def main():
    p = argparse.ArgumentParser(description="Offline native-data microscopy workbench")
    p.add_argument("--port", type=int, default=8876)
    p.add_argument("--data-root", type=Path, default=BASE / "workspace")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    # Plotly is shipped from the installed package, without network requests.
    js = BASE / "static" / "plotly.min.js"
    if not js.exists():
        from plotly.offline import get_plotlyjs
        js.write_text(get_plotlyjs(), encoding="utf-8")
    server = None
    for port in range(args.port, args.port+20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("No available local port.")
    server.state = State(args.data_root)
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={server.state.token}"
    (args.data_root / "session.json").write_text(json.dumps({
        "url": url, "port": server.server_address[1], "pid": os.getpid()}, indent=2), encoding="utf-8")
    print("Microscopy Workbench " + core.VERSION, flush=True)
    print("Local URL: " + url, flush=True)
    print("Results: " + str(server.state.outputs), flush=True)
    print("Keep this window running. Ctrl+C stops the server.", flush=True)
    if not args.no_browser:
        threading.Timer(.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in server.state.jobs.values():
            job["_event"].set()
        server.state.pool.shutdown(wait=True, cancel_futures=True)
        for ds in server.state.datasets.values():
            ds.close()
        server.server_close()


if __name__ == "__main__":
    main()
