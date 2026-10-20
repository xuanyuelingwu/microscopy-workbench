"""Run a saved configuration against the exact same source file."""
import argparse
import json
from pathlib import Path
import core


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--settings", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-different-source", action="store_true",
                   help="Explicitly allow applying a protocol to a new source; new hash is recorded.")
    a = p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        p.error("Output must be absent or empty; existing results are never overwritten.")
    cfg = json.loads(a.settings.read_text(encoding="utf-8"))
    expected = cfg.get("source_sha256")
    digest = core.sha256(a.source)
    if expected and expected != digest and not a.allow_different_source:
        p.error("Source SHA-256 differs from the saved configuration. Use the original file.")
    cfg["replay_parent_settings"] = str(a.settings.resolve())
    cfg["replay_parent_sha256"] = core.sha256(a.settings)
    cfg["source_match_original"] = expected == digest
    with_source = core.Dataset(a.source)
    try:
        with_source.hash = digest
        fn = core.make_volume if cfg.get("mode") == "volume" else core.make_video
        progress = core.Progress(lambda n, s: print(f"{n:5.1f}% {s}", flush=True))
        result = fn(with_source, cfg, a.output, progress)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        with_source.close()


if __name__ == "__main__":
    main()
