"""Reproducible native-data microscopy rendering. No data are synthesized.

ND2 is read one acquisition frame at a time. Display transforms never modify
the source or the native-pixel overlap calculations.
"""
from __future__ import annotations

import csv
import base64
import io
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
import zipfile

import imageio_ffmpeg
import nd2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from skimage.measure import marching_cubes
import tifffile

VERSION = "1.0.0"
BASE = Path(__file__).resolve().parent
MAX_STACK_BYTES = 1_600_000_000


class UserError(ValueError):
    """An actionable validation message, safe to present in the local UI."""


class Cancelled(UserError):
    pass


def plain(v):
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return plain(v.tolist())
    if isinstance(v, np.generic):
        return plain(v.item())
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, Path):
        return str(v)
    return v


def dump(path, v):
    Path(path).write_text(json.dumps(plain(v), ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding="utf-8")


def csv_write(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(plain(rows))


def sha256(path, check=lambda: None):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(8 * 1024 * 1024):
            check()
            h.update(block)
    return h.hexdigest()


def versions():
    names = ["nd2", "numpy", "scipy", "scikit-image", "tifffile", "pillow",
             "plotly", "imageio-ffmpeg"]
    return {"tool": VERSION, "python": sys.version, "platform": platform.platform(),
            "packages": {k: importlib.metadata.version(k) for k in names},
            "ffmpeg": imageio_ffmpeg.get_ffmpeg_version(),
            "code_sha256": {str(p.relative_to(BASE)).replace("\\", "/"): sha256(p)
                            for p in [BASE/"core.py", BASE/"app.py", BASE/"replay.py",
                                      BASE/"static/app.js", BASE/"static/index.html",
                                      BASE/"static/volume_viewer.html", BASE/"static/styles.css"]
                            if p.exists()}}


def number(v, name, low=None, high=None, integer=False):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(name + " 必须是有效数字。")
    if not math.isfinite(n) or (low is not None and n < low) or (
            high is not None and n > high) or (integer and n != int(n)):
        raise UserError(name + " 超出允许范围。")
    return int(n) if integer else n


def color_rgb(color):
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
        raise UserError("通道颜色必须为 #RRGGBB。")
    try:
        return np.array([int(color[i:i+2], 16) for i in (1, 3, 5)], np.float32) / 255
    except ValueError:
        raise UserError("无效的通道颜色。")


class Dataset:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.lock = threading.RLock()
        self.hash = None
        self._frame = None
        self._cached = None
        self._tiff_array = None
        if not self.path.is_file():
            raise UserError("找不到文件：" + str(self.path))
        self.source_stat = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        suffix = self.path.suffix.lower()
        self.kind = "nd2" if suffix == ".nd2" else "tiff"
        if suffix not in {".nd2", ".tif", ".tiff"}:
            raise UserError("支持 ND2 和有明确维度的 TIFF / OME-TIFF。")
        self.warnings = []
        try:
            if self.kind == "nd2":
                self._open_nd2()
            else:
                self._open_tiff()
        except Exception:
            self.close()
            raise

    def _open_nd2(self):
        self.f = nd2.ND2File(self.path)
        if self.f.is_rgb or self.f.components_per_channel != 1:
            raise UserError("暂不支持 RGB 相机 ND2；请使用独立灰度荧光通道。")
        self.sizes = dict(self.f.sizes)
        self.sizes.setdefault("C", 1)
        self.sizes.setdefault("Y", self.f.attributes.heightPx)
        self.sizes.setdefault("X", self.f.attributes.widthPx)
        self.dtype = np.dtype(self.f.dtype)
        self.bits = self.f.attributes.bitsPerComponentSignificant
        self.loops = list(self.f.loop_indices)
        self.axes = [k for k in self.sizes if k not in {"C", "Y", "X"}]
        self.lookup = {tuple(int(loop.get(k, 0)) for k in self.axes): i
                       for i, loop in enumerate(self.loops)}
        self.channel_info = []
        for c in self.f.metadata.channels:
            name = c.channel.name
            wave = c.channel.excitationLambdaNm
            col = c.channel.color
            rgb = [int(col.r), int(col.g), int(col.b)] if hasattr(col, "r") else (
                list(col)[:3] if isinstance(col, (list, tuple)) else [255]*3)
            if max(rgb, default=0) == 0:
                rgb = [255]*3
            self.channel_info.append({"name": name, "excitation_nm": wave,
                                      "color": "#" + "".join(f"{x:02x}" for x in rgb)})
        if len(self.channel_info) != self.sizes["C"]:
            raise UserError("通道元数据与图像维度不一致，停止自动解析。")
        vm = self.f.metadata.channels[0].volume
        cal = list(vm.axesCalibrated)
        vox = self.f.voxel_size()
        self.calibration = {"x_um": float(vox.x) if cal[0] else None,
                            "y_um": float(vox.y) if cal[1] else None,
                            "z_step_um": float(vox.z) if cal[2] else None}
        try:
            self.events = {int(e["Index"]): plain(e)
                           for e in self.f.events(orient="records") if "Index" in e}
        except Exception:
            self.events = {}
            self.warnings.append("事件表不可用；Z / 时间将核查帧元数据。")

    def _open_tiff(self):
        import xml.etree.ElementTree as ET
        self.f = tifffile.TiffFile(self.path)
        if len(self.f.series) != 1:
            raise UserError("当前 TIFF 有多个 series；请先导出单个 OME-TIFF series。")
        series = self.f.series[0]
        axes = series.axes
        if any(k not in "TCZYX" and n > 1 for k, n in zip(axes, series.shape)):
            raise UserError("TIFF 轴含未定义的 Q / S / I 等维度，不能猜测其为时间或 Z。请导出明确 TCZYX 的 OME-TIFF。")
        self.sizes = {k: n for k, n in zip(axes, series.shape) if n > 1}
        for k in "CYX":
            self.sizes.setdefault(k, 1)
        self.tiff_axes = axes
        self.tiff_shape = series.shape
        self.dtype = np.dtype(series.dtype)
        self.bits = self.dtype.itemsize * 8 if np.issubdtype(self.dtype, np.integer) else None
        self.axes = [k for k in axes if k not in "CYX" and self.sizes.get(k, 1) > 1]
        self.events = {}
        self.channel_info = [{"name": "Channel " + str(i+1), "excitation_nm": None,
                              "color": ["#377bff", "#ff3f50", "#33df67"][i % 3]}
                             for i in range(self.sizes["C"])]
        self.calibration = {"x_um": None, "y_um": None, "z_step_um": None}
        self.ome_planes = {}
        self.ome_dt = None
        if self.f.ome_metadata:
            root = ET.fromstring(self.f.ome_metadata)
            pixels = root.find(".//{*}Pixels")
            if pixels is not None:
                units = {"µm": 1., "um": 1., "nm": .001, "mm": 1000., "m": 1e6}
                for ax in "XYZ":
                    val = pixels.get("PhysicalSize" + ax)
                    factor = units.get(pixels.get("PhysicalSize" + ax + "Unit", "µm"))
                    if val and factor is not None:
                        key = ax.lower() + ("_step_um" if ax == "Z" else "_um")
                        self.calibration[key] = float(val) * factor
                for i, ch in enumerate(pixels.findall("{*}Channel")):
                    if i < len(self.channel_info):
                        self.channel_info[i]["name"] = ch.get("Name", self.channel_info[i]["name"])
                tfactor = {"s": 1., "ms": .001, "min": 60., "h": 3600.}
                if pixels.get("TimeIncrement"):
                    unit = tfactor.get(pixels.get("TimeIncrementUnit", "s"))
                    if unit is not None:
                        self.ome_dt = float(pixels.get("TimeIncrement")) * unit
                for p in pixels.findall("{*}Plane"):
                    key = tuple(int(p.get("The" + ax, "0")) for ax in "TZC")
                    rec = {}
                    if p.get("PositionZ") and p.get("PositionZUnit", "µm") in units:
                        rec["z_um"] = float(p.get("PositionZ")) * units[p.get("PositionZUnit", "µm")]
                    if p.get("DeltaT") and p.get("DeltaTUnit", "s") in tfactor:
                        rec["time_s"] = float(p.get("DeltaT")) * tfactor[p.get("DeltaTUnit", "s")]
                    self.ome_planes[key] = rec
        try:
            self._tiff_array = tifffile.memmap(self.path, series=0)
        except (ValueError, TypeError):
            # Avoid repeatedly decompressing a complete compressed series on each frame.
            nbytes = math.prod(series.shape) * self.dtype.itemsize
            if nbytes > MAX_STACK_BYTES:
                raise UserError("压缩 TIFF 超过当前 1.6 GB 内存上限；请转成非压缩 OME-TIFF 再打开。")
            self._tiff_array = series.asarray()
            self.warnings.append("压缩 TIFF 已解码到内存；ND2 仍为逐帧读取。")

    def close(self):
        if getattr(self, "_tiff_array", None) is not None:
            mmap = getattr(self._tiff_array, "_mmap", None)
            if mmap is not None:
                mmap.close()
        if getattr(self, "f", None) is not None:
            self.f.close()

    def check_source(self):
        st = self.path.stat()
        if (st.st_size, st.st_mtime_ns) != self.source_stat:
            raise UserError("源文件在打开后发生变化；请等待下载完成并重新选择文件，避免混用不同版本。")

    def selection(self, values=None, variable=None):
        values = values or {}
        return {k: number(values.get(k, 0), k + " 索引", 0, self.sizes[k]-1, True)
                for k in self.axes if k != variable}

    def seq(self, selection):
        key = tuple(int(selection.get(k, 0)) for k in self.axes)
        if key not in self.lookup:
            raise UserError("所选位置不存在对应的采集帧。")
        return self.lookup[key]

    def frame(self, selection=None):
        selection = self.selection(selection)
        with self.lock:
            key = tuple(selection.items())
            if key == self._cached:
                return self._frame
            if self.kind == "nd2":
                a = self.f.read_frame(self.seq(selection))
                a = a.reshape(self.sizes["C"], self.sizes["Y"], self.sizes["X"])
            else:
                ix = tuple(slice(None) if k in "CYX" else selection.get(k, 0)
                           for k in self.tiff_axes)
                a = self._tiff_array[ix]
                ax = [k for k in self.tiff_axes if k in "CYX"]
                if "C" not in ax:
                    a = a[None]
                    ax = ["C"] + ax
                a = np.transpose(a, [ax.index(k) for k in "CYX"])
            self._frame = a
            self._cached = key
            return a

    def coordinate(self, selection, channel, kind):
        with self.lock:
            return self._coordinate_unlocked(selection, channel, kind)

    def _coordinate_unlocked(self, selection, channel, kind):
        if self.kind == "nd2":
            seq = self.seq(selection)
            e = self.events.get(seq, {})
            if kind == "z":
                # Event-table stage positions track each acquisition plane.
                vals = [v for k, v in e.items() if k.startswith("Z Coord")]
                if vals and vals[0] is not None:
                    return float(vals[0]), "ND2 event-table stage Z"
            try:
                c = self.f.frame_metadata(seq).channels[channel]
                if kind == "time":
                    v = c.time.relativeTimeMs
                    if v is not None:
                        return float(v) / 1000., "ND2 channel frame timestamp"
                else:
                    return float(c.position.stagePositionUm.z), "ND2 frame stage Z"
            except (AttributeError, IndexError, TypeError, ValueError):
                pass
            if kind == "time" and e.get("Time [s]") is not None:
                return float(e["Time [s]"]), "ND2 event-table timestamp"
        else:
            p = self.ome_planes.get((selection.get("T", 0), selection.get("Z", 0), channel), {})
            v = p.get("time_s" if kind == "time" else "z_um")
            if v is not None:
                return v, "OME Plane " + ("DeltaT" if kind == "time" else "PositionZ")
            if kind == "time" and self.ome_dt:
                return selection.get("T", 0) * self.ome_dt, "OME TimeIncrement"
        return None, None

    def calibration_for(self, overrides=None):
        c = dict(self.calibration)
        for k, v in (overrides or {}).items():
            if k in c and v is not None and v != "":
                c[k] = number(v, k, 1e-9)
        return c

    def time_axis(self, selection, channel=0, override_dt=None):
        n = self.sizes.get("T", 1)
        if n < 2:
            raise UserError("此文件没有至少两帧的 T 时间维度，不能生成时间序列视频。")
        if override_dt not in (None, ""):
            dt = number(override_dt, "手动帧间隔（秒）", 1e-6)
            return np.arange(n, dtype=float) * dt, "user-specified uniform interval"
        values = [self.coordinate({**selection, "T": i}, channel, "time")
                  for i in range(n)]
        if any(v is None or not math.isfinite(v) for v, _ in values):
            raise UserError("缺少完整时间戳；请在高级设置中填写真实的帧间隔。")
        times = np.array([v for v, _ in values])
        if not np.all(np.diff(times) > 0):
            raise UserError("时间戳不严格递增；请核查所选位置或填写真实帧间隔。")
        return times, values[0][1]

    def z_axis(self, selection, channel=0, mode="auto", overrides=None):
        n = self.sizes.get("Z", 1)
        if n < 2:
            raise UserError("此文件没有至少两层的 Z 维度，不能重构三维。")
        c = self.calibration_for(overrides)
        recorded = [self.coordinate({**selection, "Z": i}, channel, "z")
                    for i in range(n)]
        coords = np.array([v if v is not None else np.nan for v, _ in recorded])
        unique = bool(np.all(np.isfinite(coords)) and np.all(np.diff(np.sort(coords)) > 1e-7))
        if mode == "recorded" and not unique:
            raise UserError("实测 Z 坐标缺失或重复；不能把这些层假定为不同位置。可明确改用已校准的名义层间距。")
        warnings = []
        if mode in ("auto", "recorded") and unique:
            src = recorded[0][1]
        else:
            step = c["z_step_um"]
            if step is None or step <= 0:
                raise UserError("没有有效的 Z 物理间隔；请填写实际采集的 Z 层间距。")
            coords = np.arange(n) * step
            src = "user-specified nominal Z" if (overrides or {}).get("z_step_um") not in (None, "") else "file-calibrated nominal Z"
            if mode == "auto":
                warnings.append("记录的逐层 Z 缺失或重复，已回退到文件校准的名义层间距。")
        order = np.argsort(coords, kind="stable")
        pos = coords[order] - np.min(coords)
        return pos, order, src, coords, warnings

    def info(self):
        sample = self.frame()
        result = {"name": self.path.name, "size_bytes": self.path.stat().st_size,
                  "kind": self.kind, "sizes": self.sizes, "axes": self.axes,
                  "dtype": self.dtype.name, "significant_bits": self.bits,
                  "channels": [], "calibration": self.calibration, "warnings": self.warnings[:],
                  "has_z": self.sizes.get("Z", 1) > 1,
                  "has_time": self.sizes.get("T", 1) > 1}
        for i, ch in enumerate(self.channel_info):
            a = sample[i]
            finite = a[np.isfinite(a)]
            if finite.size == 0:
                raise UserError("图像没有有限像素值。")
            bg = background_mode(finite)
            high = float(np.percentile(finite, 99.7))
            result["channels"].append({**ch, "index": i, "min": float(finite.min()),
                                       "max": float(finite.max()), "background": bg,
                                       "low": bg, "high": max(high, bg+1),
                                       "gate": max(150., float(np.std(finite[finite <= np.median(finite)]))*5)})
        if result["has_time"]:
            try:
                t, src = self.time_axis(self.selection(variable="T"))
                result.update(times_s=t.tolist(), time_source=src)
            except UserError as e:
                result["time_error"] = str(e)
        if result["has_z"]:
            try:
                z, order, src, raw, warnings = self.z_axis(self.selection(variable="Z"))
                result.update(z_um=z.tolist(), z_order=order.tolist(), z_source=src)
                result["warnings"] += warnings
            except UserError as e:
                result["z_error"] = str(e)
        return plain(result)


def background_mode(a):
    a = np.asarray(a)
    if np.issubdtype(a.dtype, np.integer) and a.min() >= 0 and a.max() <= 65535:
        counts = np.bincount(a.ravel().astype(np.int64), minlength=int(a.max())+1)
        return float(np.argmax(counts))
    hist, edges = np.histogram(a[np.isfinite(a)], bins=512)
    i = int(np.argmax(hist))
    return float((edges[i] + edges[i+1]) / 2)


def display_settings(ds, config):
    channels = config.get("channels")
    if not isinstance(channels, list) or not channels or len(channels) > 4:
        raise UserError("请启用 1–4 个显示通道。")
    seen = set()
    result = []
    for ch in channels:
        i = number(ch.get("index"), "通道索引", 0, ds.sizes["C"]-1, True)
        if i in seen:
            raise UserError("不能重复选择同一通道。")
        seen.add(i)
        low = number(ch.get("low", 0), "显示下限")
        high = number(ch.get("high", 4095), "显示上限")
        if high <= low:
            raise UserError("显示上限必须大于显示下限。")
        color = ch.get("color", ds.channel_info[i]["color"])
        color_rgb(color)
        result.append({"index": i, "name": ds.channel_info[i]["name"], "low": low,
                       "high": high, "gamma": number(ch.get("gamma", 1), "显示 gamma", .05, 5),
                       "color": color, "background": number(ch.get("background", 0), "背景"),
                       "gate": number(ch.get("gate", 150), "背景以上阈值", 0),
                       "opacity": number(ch.get("opacity", .35), "不透明度", 0, 1)})
    return result


def render_rgb(a, channels):
    out = np.zeros((*a.shape[-2:], 3), np.float32)
    for ch in channels:
        v = a[ch["index"]].astype(np.float32)
        if not np.all(np.isfinite(v)):
            v = np.nan_to_num(v, nan=ch["low"], posinf=ch["high"], neginf=ch["low"])
        v = np.clip((v - ch["low"]) / (ch["high"] - ch["low"]), 0, 1) ** ch["gamma"]
        out += v[..., None] * color_rgb(ch["color"])
    return np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)


def roi_values(config, width, height):
    r = config.get("roi")
    if r is None:
        return {"x": 0, "y": 0, "width": width, "height": height}
    x = number(r.get("x"), "ROI x", 0, width-1, True)
    y = number(r.get("y"), "ROI y", 0, height-1, True)
    w = number(r.get("width"), "ROI 宽", 1, width-x, True)
    h = number(r.get("height"), "ROI 高", 1, height-y, True)
    return {"x": x, "y": y, "width": w, "height": h}


def slice_roi(r):
    return (slice(r["y"], r["y"]+r["height"]), slice(r["x"], r["x"]+r["width"]))


class Progress:
    def __init__(self, callback=None, cancelled=None):
        self.callback = callback or (lambda *args: None)
        self.cancelled = cancelled or threading.Event()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("任务已取消，已完成的其他结果保留。")

    def update(self, p, message):
        self.check()
        self.callback(float(p), str(message))


def provenance(ds, config, folder, progress):
    ds.check_source()
    folder.mkdir(parents=True, exist_ok=True)
    progress.update(1, "计算源文件 SHA-256")
    if ds.hash is None:
        ds.hash = sha256(ds.path, progress.check)
    source = {"name": ds.path.name, "path_on_this_machine": str(ds.path),
              "size_bytes": ds.path.stat().st_size, "sha256": ds.hash,
              "metadata": ds.info()}
    cfg = {k: v for k, v in config.items() if k not in {"dataset", "source_path"}}
    cfg.update(schema="microscopy-workbench/1", tool_version=VERSION,
               source_sha256=ds.hash)
    dump(folder / "source.json", source)
    dump(folder / "settings.json", cfg)
    dump(folder / "software_versions.json", versions())
    return cfg


def archive(folder, progress):
    progress.update(97, "整理可复现文件与下载包")
    manifest = []
    for path in sorted(folder.rglob("*")):
        progress.check()
        if path.is_file() and path.name not in {"bundle.zip", "manifest.json"} and ".frames" not in path.parts:
            manifest.append({"path": path.relative_to(folder).as_posix(),
                             "bytes": path.stat().st_size, "sha256": sha256(path, progress.check)})
    dump(folder / "manifest.json", manifest)
    with zipfile.ZipFile(folder / "bundle.zip", "w", zipfile.ZIP_STORED) as z:
        for row in manifest:
            z.write(folder / row["path"], row["path"])
        z.write(folder / "manifest.json", "manifest.json")
    progress.update(100, "完成")
    return {"files": [x["path"] for x in manifest], "bundle": "bundle.zip"}


def timing_plan(times, start, end, zero_s, speed, fps):
    """All native frames retained. CFR MP4 uses cumulative rounded boundaries.

    Speed is capped so each dwell is >= one MP4 frame and one GIF 10-ms unit.
    The final native frame receives the median selected inter-frame interval.
    """
    times = np.asarray(times, dtype=float)
    if len(times) < 2 or not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
        raise UserError("时间轴必须含至少两帧且严格递增。")
    start = number(start, "起始帧", 0, len(times)-2, True)
    end = number(end, "终止帧", start+1, len(times)-1, True)
    speed = number(speed, "播放倍速", .001, 10000)
    fps = number(fps, "MP4 帧率", 1, 120, True)
    zero_s = number(zero_s, "计时零点（采集秒）")
    selected = times[start:end+1]
    delta = np.diff(selected)
    dwell = np.r_[delta, np.median(delta)]
    effective = min(speed, float(dwell.min()) * fps, float(dwell.min()) * 100)
    video_edges = np.rint(np.r_[0, np.cumsum(dwell / effective)] * fps).astype(np.int64)
    gif_edges = np.rint(np.r_[0, np.cumsum(dwell / effective)] * 100).astype(np.int64)
    reps, gif_units = np.diff(video_edges), np.diff(gif_edges)
    if np.any(reps < 1) or np.any(gif_units < 1):
        raise UserError("时间量化产生零时长帧，请降低倍速。")
    if np.any(gif_units > 65535):
        raise UserError("某一 GIF 原生帧停留超过格式的 655.35 秒上限；请提高倍速或缩短区间。")
    if video_edges[-1] > 360000:
        raise UserError("本次导出超过 360,000 个编码帧；请缩短区间或提高倍速。")
    rows = [{"source_T_zero_based": start+i, "source_time_s": float(t),
             "relative_time_s": float(t-zero_s), "source_dwell_s": float(dwell[i]),
             "mp4_first_frame": int(video_edges[i]), "mp4_repetitions": int(reps[i]),
             "mp4_duration_s": float(reps[i]/fps), "gif_duration_ms": int(gif_units[i]*10)}
            for i, t in enumerate(selected)]
    return {"rows": rows, "fps": fps, "requested_speed": speed, "effective_speed": effective,
            "total_encoded_frames": int(video_edges[-1]),
            "duration_mp4_s": float(video_edges[-1]/fps),
            "duration_gif_s": float(gif_units.sum()/100),
            "max_cumulative_mp4_timing_error_s": float(np.max(np.abs(
                video_edges/fps - np.r_[0, np.cumsum(dwell/effective)]))),
            "last_frame_dwell": "median of selected positive native intervals",
            "method": "native frames repeated, never temporally interpolated; MP4 CFR cumulative rounding; GIF 10 ms cumulative rounding"}


def _font(size):
    for p in [Path("C:/Windows/Fonts/arial.ttf"),
              Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def annotate(arr, relative_s, config, calibration):
    """Add a separate black footer; never obscure the acquired field."""
    im = Image.fromarray(arr)
    max_side = number(config.get("max_side", 0), "输出最长边", 0, 4096, True)
    scale = min(1., max_side / max(im.size)) if max_side else 1.
    if scale < 1:
        im = im.resize((max(1, round(im.width*scale)), max(1, round(im.height*scale))), Image.Resampling.LANCZOS)
    want_time = bool(config.get("timestamp", True))
    want_bar = bool(config.get("scale_bar", True)) and calibration.get("x_um") is not None
    if want_time or want_bar:
        font_size = max(12, min(22, round(im.width / 35)))
        font = _font(font_size)
        footer = font_size + 20
        canvas = Image.new("RGB", (max(im.width, 180), im.height + footer), "black")
        canvas.paste(im, (0, 0))
        d = ImageDraw.Draw(canvas)
        if want_time:
            d.text((8, im.height+7), f"t = {relative_s:+.2f} s", fill="white", font=font)
        if want_bar:
            target = im.width * calibration["x_um"] / scale * .20
            exponent = 10 ** math.floor(math.log10(max(target, 1e-12)))
            length = max(v*exponent for v in [1, 2, 5, 10] if v*exponent <= target)
            bar = max(1, round(length / calibration["x_um"] * scale))
            # On very narrow images put the scale annotation in a second footer row.
            if im.width < 360 and want_time:
                extra = Image.new("RGB", (canvas.width, canvas.height+font_size+15), "black")
                extra.paste(canvas, (0, 0))
                canvas, d = extra, ImageDraw.Draw(extra)
                yy = canvas.height - font_size - 7
            else:
                yy = im.height+8
            x = canvas.width - 8 - bar
            d.line((x, yy+font_size, x+bar, yy+font_size), fill="white", width=2)
            label = f"{length:g} \u00b5m"
            tw = d.textlength(label, font=font)
            d.text((canvas.width-8-tw, yy-3), label, fill="white", font=font)
        im = canvas
    # yuv420p requires even dimensions: pad, do not crop or distort data.
    if im.width % 2 or im.height % 2:
        padded = Image.new("RGB", (im.width+im.width % 2, im.height+im.height % 2), "black")
        padded.paste(im, (0, 0))
        im = padded
    return im


def encode_movie(frame_paths, timing, folder, stem, progress, p0, span):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    first = Image.open(frame_paths[0])
    width, height = first.size
    first.close()
    mp4 = folder / (stem + ".mp4")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
            "-r", str(timing["fps"]), "-i", "-", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-threads", "2", str(mp4)]
    log = folder / (stem + "_encoder.log")
    with log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=err, creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            for i, (path, row) in enumerate(zip(frame_paths, timing["rows"])):
                progress.update(p0 + span*.5*i/len(frame_paths), f"编码 {stem} MP4 · 原始帧 {i+1}/{len(frame_paths)}")
                with Image.open(path) as im:
                    data = im.convert("RGB").tobytes()
                for j in range(row["mp4_repetitions"]):
                    if j % 50 == 0:
                        progress.check()
                    proc.stdin.write(data)
            proc.stdin.close()
            if proc.wait() != 0:
                raise UserError("MP4 编码失败，详见 " + log.name)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    # GIF works from native-frame PNGs, independently of the lossy MP4.
    frames_txt = folder / ".frames" / (stem + "_concat.txt")
    lines = ["ffconcat version 1.0"]
    for path, row in zip(frame_paths, timing["rows"]):
        lines += ["file '" + path.name + "'", "option framerate 100",
                  "duration " + f"{row['gif_duration_ms']/1000:.2f}"]
    # The last PNG is a terminator for the last duration and is excluded by -t.
    lines += ["file '" + frame_paths[-1].name + "'", "option framerate 100"]
    frames_txt.write_text("\n".join(lines), encoding="utf-8")
    duration = f"{timing['duration_gif_s']:.2f}"
    # Two passes avoid retaining the whole movie in a split-filter buffer while
    # the global palette is being computed.
    palette = frames_txt.parent / (stem + "_palette.png")
    commands = [
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(frames_txt),
         "-vf", "palettegen=stats_mode=full", "-frames:v", "1",
         "-update", "1", "-threads", "2", str(palette)],
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(frames_txt),
         "-i", str(palette), "-lavfi", "paletteuse=dither=sierra2_4a",
         "-t", duration, "-fps_mode", "vfr", "-loop", "0",
         "-final_delay", str(timing["rows"][-1]["gif_duration_ms"]//10),
         "-threads", "2", str(folder / (stem + ".gif"))]]
    with log.open("a", encoding="utf-8") as err:
        for command in commands:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err,
                                    creationflags=0x08000000 if os.name == "nt" else 0)
            try:
                while proc.poll() is None:
                    progress.update(p0+span*.72, "编码 " + stem + " GIF")
                    time.sleep(.2)
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            if proc.returncode:
                raise UserError("GIF 编码失败，详见 " + log.name)
    # Decode the GIF timing to expose format quantization / duplicate merging.
    with Image.open(folder / (stem + ".gif")) as gif:
        gif_rows = []
        for i in range(gif.n_frames):
            gif.seek(i)
            gif_rows.append({"encoded_frame": i, "duration_ms": gif.info.get("duration", 0)})
    csv_write(folder / (stem + "_gif_encoded_timing.csv"), gif_rows)
    return {"width": width, "height": height, "mp4": mp4.name,
            "gif": stem+".gif", "gif_decoded_frame_count": len(gif_rows),
            "gif_decoded_duration_s": sum(r["duration_ms"] for r in gif_rows)/1000}


def make_video(ds, config, folder, progress=None):
    progress = progress or Progress()
    folder = Path(folder)
    cfg = provenance(ds, config, folder, progress)
    channels = display_settings(ds, config)
    selection = ds.selection(config.get("selection"), variable="T")
    times, time_source = ds.time_axis(selection, channels[0]["index"], config.get("time_interval_s"))
    start = config.get("start", 0)
    end = config.get("end", len(times)-1)
    zero = config.get("zero_s", float(times[0]))
    timing = timing_plan(times, start, end, zero, config.get("speed", 5), config.get("fps", 30))
    roi = roi_values(config, ds.sizes["X"], ds.sizes["Y"])
    ref = number(config.get("roi_reference_frame", start), "ROI 参考帧", 0, len(times)-1, True)
    c = ds.calibration_for(config.get("calibration"))
    views = ["full"] if config.get("preview_only") else ["full", "crop"]
    frames_dir = folder / ".frames"
    frames_dir.mkdir(exist_ok=True)
    paths = {v: [] for v in views}
    sat_rows = []
    native_rows = []
    for i, row in enumerate(timing["rows"]):
        progress.update(5 + 43*i/len(timing["rows"]), f"读取原始帧 {i+1}/{len(timing['rows'])}")
        t = row["source_T_zero_based"]
        a = ds.frame({**selection, "T": t})
        rgb = render_rgb(a, channels)
        for ch in channels:
            raw = a[ch["index"]]
            cutoff = (2**ds.bits-1) if ds.bits and np.issubdtype(raw.dtype, np.integer) else None
            sat_rows.append({"source_T_zero_based": t, "channel": ch["name"],
                             "acquisition_saturation_value": cutoff,
                             "saturated_native_pixels_full_field": int((raw >= cutoff).sum()) if cutoff else None,
                             "display_low_clipped_pixels_full_field": int((raw < ch["low"]).sum()),
                             "display_high_clipped_pixels_full_field": int((raw > ch["high"]).sum())})
            ct, ct_src = ds.coordinate({**selection, "T": t}, ch["index"], "time")
            native_rows.append({"source_T_zero_based": t, "channel": ch["name"],
                                "channel_acquisition_time_s": ct, "time_metadata_source": ct_src})
        for view in views:
            arr = rgb if view == "full" else rgb[slice_roi(roi)]
            im = annotate(arr, row["relative_time_s"], config, c)
            dest = frames_dir / f"{view}_{i:06d}.png"
            im.save(dest)
            paths[view].append(dest)
        if t in {int(start), int(end), ref}:
            Image.fromarray(rgb).save(folder / f"native_render_T{t:05d}.png")
        if i == 0:
            Image.fromarray(rgb).save(folder / "full_field_first_frame.png")
    reference = render_rgb(ds.frame({**selection, "T": ref}), channels)
    Image.fromarray(reference[slice_roi(roi)]).save(folder / "ROI_native_crop_reference.png")
    im = Image.fromarray(reference)
    d = ImageDraw.Draw(im)
    d.rectangle((roi["x"], roi["y"], roi["x"]+roi["width"]-1, roi["y"]+roi["height"]-1),
                outline="#ffdc47", width=max(1, round(min(im.size)/256)))
    im.save(folder / "ROI_reference_overlay.png")
    csv_write(folder / "native_frame_timing.csv", timing["rows"])
    csv_write(folder / "channel_acquisition_times.csv", native_rows)
    csv_write(folder / "clipping_and_saturation.csv", sat_rows)
    media = {}
    for j, v in enumerate(views):
        media[v] = encode_movie(paths[v], timing, folder, v, progress,
                                50+j*22, 21)
    cfg.update(channels=channels, selection=selection, start=int(start), end=int(end),
               zero_s=float(zero), roi=roi, roi_reference_frame=ref,
               roi_reference_source_time_s=float(times[ref]), calibration_used=c,
               time_source=time_source, timing=timing, media=media)
    dump(folder / "settings.json", cfg)
    methods = (
        "原始数据未修改。ND2 按原始采集帧逐帧读取；固定位置 / 固定 Z 平面，未做 Z 投影或时间插值。\n"
        "显示：每通道 clip((I-low)/(high-low),0,1)^gamma，乘所选颜色后相加并截到 RGB 0–1；"
        "整个视频共享同一组 LUT。该显示转换不用于定量。\n"
        "ROI 为原生像素半开区间 [x,x+width) × [y,y+height)，全部帧固定同一位置。"
        "没有自动漂移校正，用户可自行选择覆盖运动范围的 ROI。\n"
        "时间以首个启用通道的采集记录为参考；各通道记录另存 CSV。时间零点独立于区间起点。"
        "手动帧间隔覆盖时在 settings.json 明确记录。\n"
        "MP4 使用 H.264 CRF18、yuv420p、固定帧率；通过重复原始帧表达不等间隔采样，不生成中间图像。"
        "GIF 独立从原始渲染 PNG 编码，使用全局调色板和 10 ms 时间量化；浏览器可限制 GIF 最短帧时长。"
        "若倍速会跳过源帧则自动降低有效倍速。最后一帧停留时间取所选相邻间隔中位数。\n"
        "比例尺与时间文字加在黑色页脚，不覆盖显微图像。需要偶数尺寸时仅补黑边；"
        "只有用户设置最长边时才作 Lanczos 缩小，绝不放大。输出尺寸见 settings.json。\n"
        "无标注的原生 RGB 参考图保留于 PNG；视频是观察用衍生文件，测量应回到原始数据。\n"
        "复现：python replay.py --source <原始文件> --settings <本目录/settings.json> --output <新目录>\n"
    )
    (folder / "METHODS.txt").write_text(methods, encoding="utf-8")
    ds.check_source()
    safe_frames = frames_dir.resolve()
    if safe_frames.name != ".frames" or safe_frames.parent != folder.resolve():
        raise UserError("临时目录位置异常，未执行清理。")
    shutil.rmtree(safe_frames)
    ds.check_source()
    result = archive(folder, progress)
    return {**result, "mode": "video", "media": media,
            "timing_summary": {k: v for k, v in timing.items() if k != "rows"}}


def overlap_metrics(volumes, channels, x_um, y_um):
    if len(volumes) < 2:
        return None, None
    area = x_um*y_um if x_um is not None and y_um is not None else 1.
    rows = []
    classes = np.empty(volumes[0].shape, dtype=np.uint8)
    # Compute one plane at a time, accumulating float64 sums without allocating
    # two float64 copies of a potentially large stack.
    for index in range(volumes[0].shape[0]):
        corrected = [np.maximum(v[index].astype(np.float64)-ch["background"], 0)
                     for v, ch in zip(volumes[:2], channels[:2])]
        masks = [v > ch["gate"] for v, ch in zip(corrected, channels)]
        shared = masks[0] & masks[1]
        total = [float(v[m].sum())*area for v, m in zip(corrected, masks)]
        used = [float(v[shared].sum())*area for v in corrected]
        rows.append({"plane_sorted_index": index,
                     "native_overlap_samples": int(shared.sum()),
                     "channel_1_total": total[0], "channel_2_total": total[1],
                     "channel_1_overlap": used[0], "channel_2_overlap": used[1],
                     "channel_1_overlap_percent": 100*used[0]/total[0] if total[0] else None,
                     "channel_2_overlap_percent": 100*used[1]/total[1] if total[1] else None,
                     "pooled_overlap_percent": 100*sum(used)/sum(total) if sum(total) else None,
                     "integral_units": "a.u. um^2, summed over acquired planes" if x_um and y_um else "a.u. pixel, summed over acquired planes"})
        classes[index] = masks[0].astype(np.uint8) + masks[1].astype(np.uint8)*2
    all_row = {"plane_sorted_index": "all", "integral_units": rows[0]["integral_units"]}
    for key in ["native_overlap_samples", "channel_1_total", "channel_2_total",
                "channel_1_overlap", "channel_2_overlap"]:
        all_row[key] = sum(r[key] for r in rows)
    for ch in [1,2]:
        den = all_row[f"channel_{ch}_total"]
        all_row[f"channel_{ch}_overlap_percent"] = (
            100*all_row[f"channel_{ch}_overlap"]/den if den else None)
    den = all_row["channel_1_total"] + all_row["channel_2_total"]
    all_row["pooled_overlap_percent"] = (
        100*(all_row["channel_1_overlap"]+all_row["channel_2_overlap"])/den if den else None)
    return [all_row]+rows, classes


def point_trace(volume, ch, z_um, x_um, y_um, stride, cap, mask=None, name=None, color=None):
    # Block selection takes a real qualifying native pixel, never a block mean.
    mask = (volume.astype(np.float32)-ch["background"] > ch["gate"]) if mask is None else mask
    xyz = []
    for iz in range(len(z_um)):
        yy, xx = np.nonzero(mask[iz])
        if len(xx):
            block = (yy//stride)*((volume.shape[2]+stride-1)//stride)+(xx//stride)
            _, first = np.unique(block, return_index=True)
            xyz.append(np.column_stack((np.full(len(first), iz), yy[first], xx[first])))
    points = np.concatenate(xyz) if xyz else np.empty((0, 3), dtype=int)
    count = len(points)
    if count > cap:
        points = points[np.linspace(0, count-1, cap, dtype=int)]
    return {"type": "scatter3d", "mode": "markers", "name": name or ch["name"],
            "meta": {"channel_index": ch.get("index")},
            "x": np.round(points[:, 2]*x_um, 6).tolist(),
            "y": np.round(points[:, 1]*y_um, 6).tolist(),
            "z": np.round(z_um[points[:, 0]], 6).tolist(),
            "marker": {"size": 2, "color": color or ch["color"], "opacity": ch["opacity"]},
            "hovertemplate": "x=%{x:.3f} µm<br>y=%{y:.3f} µm<br>z=%{z:.3f} µm<extra>%{fullData.name}</extra>",
            "_display_points": len(points), "_qualifying_blocks": count}


def write_ply(path, vertices, faces):
    with Path(path).open("w", encoding="ascii") as f:
        f.write("ply\nformat ascii 1.0\nelement vertex " + str(len(vertices)) +
                "\nproperty float x\nproperty float y\nproperty float z\nelement face " +
                str(len(faces)) + "\nproperty list uchar int vertex_indices\nend_header\n")
        np.savetxt(f, vertices, fmt="%.7f")
        np.savetxt(f, np.column_stack((np.full(len(faces), 3), faces)), fmt="%d")


def surface_trace(volume, ch, z_um, x_um, y_um, step, ply):
    level = ch["background"] + ch["gate"]
    if min(volume.shape) < 2 or not float(volume.min()) < level < float(volume.max()):
        return None, {"channel": ch["name"], "reason": "threshold does not cross intensity range",
                      "vertices": 0, "faces": 0, "step_size": step}
    if step >= min(volume.shape):
        raise UserError("等值面步长大于最短维度可用间隔；请改为步长 1。")
    vertices, faces, _, _ = marching_cubes(volume.astype(np.float32), level=level,
                                          step_size=step, allow_degenerate=False)
    vertices[:, 0] = np.interp(vertices[:, 0], np.arange(len(z_um)), z_um)
    if len(faces) > 1_500_000:
        raise UserError("单通道表面超过 150 万三角面；请缩小 ROI、提高阈值或选择较大显示步长后重试。")
    xyz = vertices[:, [2, 1, 0]].astype(np.float64)
    xyz[:, 0] *= x_um
    xyz[:, 1] *= y_um
    write_ply(ply, xyz, faces)
    trace = {"type": "mesh3d", "name": ch["name"], "x": np.round(xyz[:, 0], 6).tolist(),
             "meta": {"channel_index": ch.get("index")},
             "y": np.round(xyz[:, 1], 6).tolist(), "z": np.round(xyz[:, 2], 6).tolist(),
             "i": faces[:, 0].tolist(), "j": faces[:, 1].tolist(), "k": faces[:, 2].tolist(),
             "color": ch["color"], "opacity": ch["opacity"], "flatshading": False,
             "lighting": {"ambient": .65, "diffuse": .8, "specular": .15},
             "hovertemplate": "x=%{x:.3f} µm<br>y=%{y:.3f} µm<br>z=%{z:.3f} µm<extra>%{fullData.name}</extra>"}
    return trace, {"channel": ch["name"], "level_raw": level, "vertices": len(vertices),
                   "faces": len(faces), "step_size": step, "file": ply.name}


def make_volume(ds, config, folder, progress=None):
    progress = progress or Progress()
    folder = Path(folder)
    cfg = provenance(ds, config, folder, progress)
    channels = display_settings(ds, config)
    if len(channels) > 2:
        raise UserError("三维工具每次选择 1–2 个通道，便于独立调整和核查共现。")
    selection = ds.selection(config.get("selection"), variable="Z")
    c = ds.calibration_for(config.get("calibration"))
    if not c["x_um"] or not c["y_um"]:
        raise UserError("缺少 XY 物理校准；请填写真实的 X、Y 像素尺寸（µm）。")
    z, order, zsrc, raw_z, warnings = ds.z_axis(selection, channels[0]["index"],
                                               config.get("z_mode", "auto"), config.get("calibration"))
    roi = roi_values(config, ds.sizes["X"], ds.sizes["Y"])
    bytes_needed = len(channels)*len(z)*roi["width"]*roi["height"]*ds.dtype.itemsize
    if bytes_needed > MAX_STACK_BYTES:
        raise UserError("所选体数据超过当前 1.6 GB 内存上限；请先缩小 ROI。")
    volumes = [np.empty((len(z), roi["height"], roi["width"]), dtype=ds.dtype) for _ in channels]
    plane_rows = []
    for i, iz in enumerate(order):
        progress.update(5+24*i/len(z), f"读取实测 Z 层 {i+1}/{len(z)}")
        a = ds.frame({**selection, "Z": int(iz)})
        for v, ch in zip(volumes, channels):
            v[i] = a[ch["index"]][slice_roi(roi)]
            if not np.all(np.isfinite(v[i])):
                raise UserError("体数据包含 NaN / Inf，停止自动重构。")
        plane_rows.append({"sorted_plane_zero_based": i, "source_Z_zero_based": int(iz),
                           "recorded_or_nominal_z_um": float(raw_z[iz]), "relative_z_um": float(z[i]),
                           "coordinate_source": zsrc})
    csv_write(folder / "native_Z_coordinates.csv", plane_rows)
    progress.update(31, "计算全部原生像素的阈值共现")
    overlap, classes = overlap_metrics(volumes, channels, c["x_um"], c["y_um"])
    if overlap:
        csv_write(folder / "native_overlap.csv", overlap)
        tifffile.imwrite(folder / "native_overlap_mask.tif", (classes == 3).astype(np.uint8),
                         metadata={"axes": "ZYX"}, compression="zlib")
    np.savez_compressed(folder / "native_voxels.npz", **{
        "channel_"+str(ch["index"]): v for ch, v in zip(channels, volumes)},
        z_um=z, source_z_indices=order, x_um=c["x_um"], y_um=c["y_um"],
        roi_xywh=np.array([roi[k] for k in ["x", "y", "width", "height"]]))
    # OME's nominal Z is accompanied by each actual plane center.
    nominal = c["z_step_um"] or float(np.median(np.diff(z)))
    tifffile.imwrite(folder / "native_stack.ome.tif", np.stack(volumes, axis=1),
                     ome=True, photometric="minisblack", compression="zlib",
                     metadata={"axes": "ZCYX", "PhysicalSizeX": c["x_um"],
                               "PhysicalSizeY": c["y_um"], "PhysicalSizeZ": nominal,
                               "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm",
                               "PhysicalSizeZUnit": "µm",
                               "Channel": {"Name": [ch["name"] for ch in channels]},
                               "Plane": {"PositionZ": np.repeat(z, len(channels)).tolist(),
                                         "PositionZUnit": ["µm"]*(len(z)*len(channels))},
                               "Description": "Native values; source Z indices and measured centers in native_Z_coordinates.csv; nominal PhysicalSizeZ is not a resampling."})
    stride = number(config.get("point_stride", 4), "原生点 XY 区块边长", 1, 64, True)
    cap = number(config.get("point_cap", 100000), "每通道显示点上限", 100, 500000, True)
    step = number(config.get("surface_step", 1), "等值面步长", 1, 4, True)
    native, surfaces, meshes, point_info = [], [], [], []
    sat = []
    for i, (v, ch) in enumerate(zip(volumes, channels)):
        progress.update(40+i*20, "构建 " + ch["name"] + " 原生位置点与等值面")
        p = point_trace(v, ch, z, c["x_um"], c["y_um"], stride, cap)
        point_info.append({"channel": ch["name"], "display_points": p.pop("_display_points"),
                           "qualifying_blocks": p.pop("_qualifying_blocks")})
        native.append(p)
        trace, mesh = surface_trace(v, ch, z, c["x_um"], c["y_um"], step,
                                    folder / ("surface_channel_"+str(ch["index"])+".ply"))
        meshes.append(mesh)
        if trace:
            surfaces.append(trace)
        satval = 2**ds.bits-1 if ds.bits and np.issubdtype(v.dtype, np.integer) else None
        sat.append({"channel": ch["name"], "saturation_value": satval,
                    "saturated_native_samples": int((v >= satval).sum()) if satval else None})
    if classes is not None:
        ch = {**channels[0], "opacity": 1.}
        p = point_trace(volumes[0], ch, z, c["x_um"], c["y_um"], stride, cap,
                        classes == 3, "Same-position overlap", "#ffd84a")
        p["meta"] = {"channel_index": None}
        point_info.append({"channel": "overlap", "display_points": p.pop("_display_points"),
                           "qualifying_blocks": p.pop("_qualifying_blocks")})
        native.append(p)
    progress.update(82, "保存交互视图及原始切片")
    # Native XY images use channel LUTs. No fake layers are inserted.
    slices_dir = folder / "slices"
    slices_dir.mkdir(exist_ok=True)
    local_ch = [{**ch, "index": i} for i, ch in enumerate(channels)]
    for iz in range(len(z)):
        progress.check()
        Image.fromarray(render_rgb(np.stack([v[iz] for v in volumes]), local_ch)).save(slices_dir / f"z_{iz:04d}.png")
        if classes is not None:
            palette = np.array([[0,0,0],[45,120,255],[255,64,82],[255,216,74]], dtype=np.uint8)
            Image.fromarray(palette[classes[iz]]).save(slices_dir / f"class_{iz:04d}.png")
    Image.fromarray(render_rgb(np.stack([v.max(0) for v in volumes]), local_ch)).save(folder / "MIP_display_only.png")
    payload = {"native": native, "surface": surfaces, "channels": channels,
               "z_um": z.tolist(), "shape_zyx": list(volumes[0].shape),
               "extent_um": [roi["width"]*c["x_um"], roi["height"]*c["y_um"], float(z[-1])],
               "overlap": overlap[0] if overlap else None, "warnings": warnings,
               "point_info": point_info, "meshes": meshes,
               "source_name": ds.path.name, "z_source": zsrc, "saturation": sat}
    # A portable viewer embeds small nearest-neighbour previews. Full native
    # slice PNGs and raw intensities remain in separate quantitative backups.
    def embedded(path):
        with Image.open(path) as im:
            im.thumbnail((512, 512), Image.Resampling.NEAREST)
            stream = io.BytesIO()
            im.save(stream, format="PNG")
        return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
    payload["slices"] = [embedded(slices_dir / f"z_{i:04d}.png") for i in range(len(z))]
    payload["class_slices"] = ([embedded(slices_dir / f"class_{i:04d}.png") for i in range(len(z))]
                               if classes is not None else [])
    payload["slice_preview_max_side"] = 512
    dump(folder / "scene.json", payload)
    template = (BASE / "static" / "volume_viewer.html").read_text(encoding="utf-8")
    # One standalone HTML, with local Plotly bundled and its own serialized scene.
    from plotly.offline import get_plotlyjs
    viewer = template.replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__SCENE_JSON__", json.dumps(plain(payload), ensure_ascii=False).replace("</", "<\\/"))
    (folder / "viewer.html").write_text(viewer, encoding="utf-8")
    cfg.update(channels=channels, selection=selection, roi=roi, calibration_used=c,
               z_coordinate_source=zsrc, z_order=order.tolist(), z_um=z.tolist(),
               warnings=warnings, point_info=point_info, meshes=meshes, saturation=sat)
    dump(folder / "settings.json", cfg)
    (folder / "METHODS.txt").write_text(
        "方法 1：阈值筛选后的原生采样位置点；每层每 XY 区块取一个真实合格像素。"
        "显示点上限仅影响显示，全部原生像素参与统计。物理坐标为 x*pixelX, y*pixelY, 记录 Z；"
        "所有通道按同一个 Z 排序一起重排。\n"
        "方法 2：原始强度的 Marching cubes 等值面；相邻采样位置间线性定位表面，"
        "不平滑、不去卷积、不进行超分辨率处理。step_size=1 时使用全部 XY 网格；"
        "更大步长仅是明确选择的显示简化。表面 Z 索引线性映射到记录的层中心。\n"
        "阈值为 I-background > gate（严格大于）；背景为可编辑的单通道常数。"
        "同一 XYZ 双通道同时超阈值定义表观共现。积分使用 max(I-background,0)；"
        "每通道重叠积分 / 该通道全部超阈值积分；合并百分比为两通道重叠积分之和 / 两通道全部积分之和。"
        "分母为零时结果缺失，不伪记为 0%。积分按每个原生像素 XY 面积加权后跨实测层求和，"
        "不是连续空间体积积分。原始通道增益和染料差异会影响 pooled 百分比。\n"
        "共现不是结合证据，表面相交不参与定量。透明度、颜色、gamma 和点采样密度不改变定量。"
        "同一二维坐标不同 Z 的信号不算重叠，MIP 只作展示。\n"
        "原生 XY 切片、阈值分类切片、完整 NPZ / OME-TIFF、层坐标、阈值、源文件哈希与软件版本均保留。"
        "OME PhysicalSizeZ 为名义间距；不均匀实际中心见 Plane PositionZ 与 CSV。\n"
        "复现：python replay.py --source <原始文件> --settings <本目录/settings.json> --output <新目录>\n",
        encoding="utf-8")
    ds.check_source()
    result = archive(folder, progress)
    return {**result, "mode": "volume", "overlap": payload["overlap"],
            "warnings": warnings, "viewer": "viewer.html", "scene": "scene.json"}
