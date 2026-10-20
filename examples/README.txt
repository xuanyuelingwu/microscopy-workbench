All files in this directory are SYNTHETIC software demonstrations, not acquired biological data.
Generate again: python generate_demo.py (fixed seed 20261019).
Upload either OME-TIFF in the browser, or replay its saved configuration:
python replay.py --source examples/SYNTHETIC_nonuniform_Z.ome.tif --settings examples/volume_settings.json --output demo_volume
python replay.py --source examples/SYNTHETIC_irregular_time.ome.tif --settings examples/video_settings.json --output demo_video
expected_results.json gives independently computed native-pixel overlap and recorded coordinates.
