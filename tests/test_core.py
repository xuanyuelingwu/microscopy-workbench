"""Meaningful numerical / geometry / timing regression tests, no source edits."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image
import tifffile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
TEMP = Path(__file__).resolve().parent / "_temp"
TEMP.mkdir(exist_ok=True)


class Numerics(unittest.TestCase):
    def test_overlap_integrals_and_strict_gate(self):
        a = np.array([[[10,110,210,100]]], dtype=np.uint16)
        b = np.array([[[10,210,10,100]]], dtype=np.uint16)
        ch = [{"background": 10, "gate": 50}]*2
        rows, classes = core.overlap_metrics([a,b], ch, .5, .2)
        r = rows[0]
        self.assertAlmostEqual(r["channel_1_total"], 39)
        self.assertAlmostEqual(r["channel_2_total"], 29)
        self.assertAlmostEqual(r["channel_1_overlap"], 19)
        self.assertAlmostEqual(r["channel_1_overlap_percent"], 190/390*100)
        self.assertAlmostEqual(r["channel_2_overlap_percent"], 100)
        self.assertAlmostEqual(r["pooled_overlap_percent"], 480/680*100)
        np.testing.assert_array_equal(classes, [[[0,3,1,3]]])
        ch = [{"background":10,"gate":100}]*2
        rows, _ = core.overlap_metrics([a,b], ch, 1, 1)
        self.assertEqual(rows[0]["native_overlap_samples"], 0)
        empty = np.zeros_like(a)
        rows, _ = core.overlap_metrics([empty,empty], ch, 1, 1)
        self.assertIsNone(rows[0]["pooled_overlap_percent"])

    def test_native_points_are_actual_qualified_positions(self):
        a = np.zeros((3,9,11), dtype=np.uint16)
        a[0,1,2]=500; a[0,2,3]=700; a[2,8,10]=900
        ch={"background":10,"gate":150,"name":"A","color":"#ff0000","opacity":.5}
        z = np.array([0.,.4,1.1])
        p = core.point_trace(a,ch,z,.13,.21,4,100)
        for x,y,zz in zip(p["x"],p["y"],p["z"]):
            ix,iy,iz = round(x/.13),round(y/.21),int(np.argmin(np.abs(z-zz)))
            self.assertGreater(a[iz,iy,ix]-10,150)
        self.assertEqual(p["_display_points"],2)
        p = core.point_trace(a,ch,z,.13,.21,1,2)
        self.assertEqual(p["_display_points"],2)

    def test_surface_nonuniform_z_is_linear_between_native_centers(self):
        volume = np.broadcast_to(np.array([0.,10.,30.])[:,None,None],(3,4,5)).copy()
        ch={"background":0,"gate":20,"name":"A","color":"#ff0000","opacity":.5}
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            p,m = core.surface_trace(volume,ch,np.array([0.,2.,6.]),.2,.3,1,Path(tmp)/"x.ply")
            np.testing.assert_allclose(p["z"],4.,atol=1e-6)
            self.assertAlmostEqual(max(p["x"]),.8)
            self.assertAlmostEqual(max(p["y"]),.9)
            self.assertGreater(m["faces"],0)

    def test_timing_retains_all_frames_and_independent_zero(self):
        t=np.array([3.,3.001,4.,5.8,9.])
        p=core.timing_plan(t,1,4,9.,100,30)
        self.assertTrue(all(r["mp4_repetitions"]>=1 for r in p["rows"]))
        self.assertTrue(all(r["gif_duration_ms"]>=10 for r in p["rows"]))
        self.assertEqual(p["rows"][0]["relative_time_s"],3.001-9.)
        self.assertLessEqual(p["max_cumulative_mp4_timing_error_s"],1/60+1e-8)
        p=core.timing_plan(t,0,2,0.,100,30)
        self.assertAlmostEqual(p["effective_speed"],.03)
        with self.assertRaises(core.UserError):
            core.timing_plan([0,0,1],0,2,0,1,30)

    def test_odd_roi_is_not_cropped_for_encoder(self):
        a=np.full((5,3,3),[112,58,9],np.uint8)
        im=core.annotate(a,0,{"timestamp":False,"scale_bar":False},{"x_um":None})
        self.assertEqual(im.size,(4,6))
        np.testing.assert_array_equal(np.array(im)[:5,:3],a)
        with self.assertRaises(core.UserError):
            core.roi_values({"roi":{"x":1,"y":2,"width":100,"height":2}},20,20)

    def test_display_lut_is_fixed_and_input_unchanged(self):
        a=np.array([[[10,60,110]]],np.uint16);saved=a.copy()
        ch=[{"index":0,"low":10,"high":110,"gamma":1,"color":"#ff0000"}]
        np.testing.assert_array_equal(core.render_rgb(a,ch),[[[0,0,0],[128,0,0],[255,0,0]]])
        np.testing.assert_array_equal(a,saved)

    def test_ome_axes_and_units_and_channel_times(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp)/"series.ome.tif"
            arr=np.arange(2*3*2*7*9,dtype=np.uint16).reshape(2,3,2,7,9)
            tifffile.imwrite(path,arr,ome=True,photometric="minisblack",metadata={
                "axes":"TZCYX","PhysicalSizeX":200,"PhysicalSizeXUnit":"nm",
                "PhysicalSizeY":300,"PhysicalSizeYUnit":"nm",
                "PhysicalSizeZ":.5,"PhysicalSizeZUnit":"µm","TimeIncrement":2.5})
            d=core.Dataset(path)
            try:
                np.testing.assert_array_equal(d.frame({"T":1,"Z":2}),arr[1,2])
                self.assertAlmostEqual(d.calibration["x_um"],.2)
                self.assertAlmostEqual(d.calibration["y_um"],.3)
                t,_=d.time_axis({"Z":0});np.testing.assert_array_equal(t,[0,2.5])
                z,order,_,_,warnings=d.z_axis({"T":0})
                np.testing.assert_array_equal(z,[0,.5,1.])
                self.assertEqual(len(warnings),1)
            finally:d.close()

    def test_ambiguous_tiff_axes_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            p=Path(tmp)/"undefined.tif"
            tifffile.imwrite(p,np.zeros((4,8,9),np.uint16),photometric="minisblack",metadata={"axes":"QYX"})
            with self.assertRaises(core.UserError):core.Dataset(p)


if __name__=="__main__":
    unittest.main(verbosity=2)
