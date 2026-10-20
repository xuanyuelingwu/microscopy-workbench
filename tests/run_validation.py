"""Run the portable suite and write a path-free release validation report."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import platform
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]


def main():
    started=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern="test_*.py")
    result=unittest.TextTestRunner(stream=sys.stdout,verbosity=2).run(suite)
    packages=["nd2","numpy","scipy","scikit-image","tifffile","pillow","plotly","imageio-ffmpeg"]
    record={"date":"2026-10-20","version":"1.0.0","environment":"fresh virtual environment installed from public PyPI",
            "python":platform.python_version(),"platform":platform.system(),"architecture":platform.machine(),
            "tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
            "skipped":len(result.skipped),"passed":result.wasSuccessful(),
            "duration_s":round(time.perf_counter()-started,3),
            "packages":{p:metadata.version(p) for p in packages},
            "code_sha256":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ["core.py","app.py","replay.py","package_release.py"]},
            "input_data":"included synthetic OME-TIFFs and generated in-test arrays only",
            "ci":"See the repository Actions checks for Windows/Linux results at the relevant commit.",
            "independent_laboratory_validation":False,"experimental_images_distributed":False}
    (ROOT/"validation/RELEASE_VALIDATION.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8",newline="\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=="__main__":main()
