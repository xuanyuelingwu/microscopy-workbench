Microscopy Workbench 1.0
Local interactive 3D rendering and time-series video export

Run start.bat on Windows. Python 3.12 and the pinned packages in requirements.txt are required.
install.bat creates a private environment on a new machine. Once installed, the app runs offline.
The HTML interface communicates only with a Python service bound to 127.0.0.1.
Keep the service window open while working. Source data are never sent to an external server.

Choose a native ND2 or a single-series, explicitly calibrated OME-TIFF. ND2 is read one acquisition
frame at a time. RGB-camera ND2 and ambiguous TIFF Q / I / S axes are rejected. Other dimensions,
such as stage position, time or Z, are fixed explicitly. Completed downloads are required.
File selection copies to workspace/uploads; direct local-path mode avoids copying large inputs.

Time series
An initial full-field movie is generated from the complete series. Display limits and gamma remain
fixed across all frames. Use the native-frame slider or locate a moment in the video, then load
that original frame. Draw an ROI on any frame, move / resize its corners, or enter native XYWH.
The same fixed ROI is applied to every selected frame; no automatic tracking is performed.
Choose an inclusive frame interval and an independent time zero, including a zero outside the clip.
Export both full-field and cropped GIF / MP4. Each native frame is retained. CFR MP4 repeats native
frames to approximate irregular sampling; GIF uses 10-ms timing. Requested speed is reduced if
necessary to avoid omitting a source frame. The last frame receives the median selected native
interval. Separate footer labels preserve image content. Odd dimensions are padded, not cropped.
The optional maximum side only downsizes images; the tool does not create higher spatial resolution.

Three dimensions
The native-position method displays actual qualifying acquired pixels in calibrated XYZ.
Display point sampling is explicit and does not change native-pixel calculations. The second method
uses marching-cubes intensity isosurfaces, with linear positioning between acquired samples.
Recorded nonuniform Z coordinates are retained. If unavailable, a calibrated nominal Z spacing
is used only with an explicit recorded fallback. No deconvolution, smoothing or super-resolution
is applied. Default mesh step is one. Users can independently change channel opacity and inspect
native XY slices and same-position overlap. Gold points require both channels at the same acquired
XYZ to exceed their background-corrected thresholds. Surface intersections are not quantified.
Directional and pooled overlap fractions use background-corrected native intensities multiplied
by XY pixel area and summed over acquired planes. This is not a continuous 3D volume integral.
Pooled channel weights remain acquisition-dependent. Coincidence does not establish molecular binding.

Reproducibility
Each task receives a new directory under workspace/outputs. Results include source SHA-256,
settings.json, software_versions.json, code hashes, METHODS.txt, numerical CSVs, native references,
per-file checksums and a result ZIP. Original ND2 files are not included in the result ZIP.
Replay a configuration with:
python replay.py --source "source.nd2" --settings "result/settings.json" --output "new_directory"
The exact source hash is required by default. Applying a protocol to a different source requires
--allow-different-source. Numerical definitions and frame maps can be reproduced; lossy encoded
bytes need not be identical across operating systems or encoder builds.

Validation and sharing
examples/ contains clearly labelled SYNTHETIC OME-TIFFs, not experimental data: one nonuniform-Z
stack and one irregular-time series, with fixed-seed generation, configurations and expected values.
Run python -m unittest discover -s tests -p "test_*.py" -v.
Numerical and real-ND2 validation scope is documented in validation/VALIDATION_SUMMARY.json.
The release does not claim independent laboratory validation or community adoption.
The community ZIP excludes project microscopy data, workspace caches and private source paths.
Tool code is MIT-licensed; dependencies retain their own licenses. See LICENSE,
THIRD_PARTY_NOTICES.txt and CITATION.cff. Practical memory / mesh limits and inference boundaries
are stated in the in-app guide and README.txt.
