"""Portable end-to-end checks using synthetic, non-biological inputs."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

BASE=Path(__file__).resolve().parents[1]
TEMP=BASE/"tests/_temp"
TEMP.mkdir(exist_ok=True)


class SyntheticIntegration(unittest.TestCase):
    def test_nonuniform_native_stack_export(self):
        examples=BASE/"examples"
        cfg=json.loads((examples/"volume_settings.json").read_text(encoding="utf-8"))
        expected=json.loads((examples/"expected_results.json").read_text(encoding="utf-8"))
        d=core.Dataset(examples/"SYNTHETIC_nonuniform_Z.ome.tif")
        try:
            with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
                result=core.make_volume(d,cfg,Path(tmp))
                o=result["overlap"]
                np.testing.assert_allclose(
                    [o["channel_1_overlap_percent"],o["channel_2_overlap_percent"],o["pooled_overlap_percent"]],
                    expected["overlap_percent"],rtol=1e-12)
                with np.load(Path(tmp)/"native_voxels.npz") as saved:
                    np.testing.assert_allclose(saved["z_um"],expected["z_um"])
                    np.testing.assert_array_equal(saved["channel_0"][3],d.frame({"Z":3})[0])
        finally:d.close()

    def test_irregular_time_crop_gif_export(self):
        examples=BASE/"examples"
        cfg=json.loads((examples/"video_settings.json").read_text(encoding="utf-8"))
        d=core.Dataset(examples/"SYNTHETIC_irregular_time.ome.tif")
        try:
            with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
                core.make_video(d,cfg,Path(tmp))
                s=json.loads((Path(tmp)/"settings.json").read_text(encoding="utf-8"))
                self.assertEqual(s["roi_reference_frame"],12)
                self.assertGreater(s["roi_reference_frame"],s["end"])
                self.assertEqual(len(s["timing"]["rows"]),10)
                self.assertLess(s["timing"]["rows"][0]["relative_time_s"],0)
                with Image.open(Path(tmp)/"crop.gif") as gif:
                    duration=0
                    for i in range(gif.n_frames):
                        gif.seek(i);duration+=gif.info["duration"]
                    self.assertEqual(gif.n_frames,10)
                    self.assertAlmostEqual(duration/1000,s["timing"]["duration_gif_s"],places=2)
        finally:d.close()


if __name__=="__main__":unittest.main(verbosity=2)
