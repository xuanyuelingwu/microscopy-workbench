# Processing definitions and limits

These definitions describe the implemented software. They do not establish the biological validity of an acquisition, threshold or experimental comparison.

## Acquired data and coordinates

ND2 is accessed through the `nd2` Python library by native acquisition frame. Additional dimensions are fixed explicitly. OME-TIFF must contain one unambiguous grayscale series; physical units are converted to micrometres and time to seconds.

For Z stacks, recorded positions are used when finite and unique, sorted by position, and expressed relative to the lowest acquired plane. An explicit nominal-spacing mode is also available. When automatic mode falls back from missing/repeated Z positions to calibrated nominal spacing, that decision is recorded. No extra acquired layers are invented.

Source arrays are retained for numerical measurements. Display transforms, colours and opacity are separate from those measurements. Valid physical metadata or known user overrides are required; pixel counts are not silently interpreted as micrometres.

## Native-position display

Each displayed point refers to an actual acquired pixel at its calibrated XYZ coordinate, selected by a background-corrected strict intensity gate. XY-block selection and a per-channel point cap can reduce the number of displayed points. These settings do not subsample the arrays used for numerical overlap.

Inspect acquired XY slices alongside a 3D view. A sparse or anisotropic acquisition remains sparse or anisotropic after rendering. This is a display of recorded fluorescence, not localization microscopy.

## Isosurfaces

Marching cubes extracts an intensity isosurface at background plus the chosen excess-intensity gate. Surface vertices are interpolated between sampled positions. Native nonuniform Z coordinates are mapped to physical Z after extraction; XY scale is calibrated independently. A larger user-selected mesh step simplifies the surface. Default step is one.

No deconvolution, smoothing or super-resolution is applied. Surface extent, apparent contact and mesh intersection are not substitutes for native-sample measurements. The implementation uses [scikit-image marching cubes](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.marching_cubes).

## Thresholded directional and pooled overlap

For channel c, let E_c = max(I_c − B_c, 0), where I is native intensity and B is the chosen constant background. A_c contains acquired samples with E_c strictly greater than gate g_c. For two channels, O = A_1 ∩ A_2 at the **same native XYZ sample**.

For calibrated XY pixel area dA, the quantities saved are:

```text
T_c = dA × sum over A_c of E_c
U_c = dA × sum over O of E_c
Directional overlap_c (%) = 100 × U_c / T_c
Pooled overlap (%) = 100 × (U_1 + U_2) / (T_1 + T_2)
```

Sums span acquired planes. There is no Z-spacing or inferred voxel-thickness weighting, so these are intensity × XY-area sums, not continuous 3D volume integrals. A zero denominator is undefined and is retained as null rather than zero. Display point caps and channel opacity do not change these numbers.

Channel backgrounds and gates are user-reviewable. The initial estimate and gate are not calibrated for every microscope. Pooled percentages retain the relative contributions of the two recorded channels and depend on acquisition gain, labeling and signal abundance. Same-position fluorescence is not proof of molecular binding. See [Dunn et al., 2011](https://doi.org/10.1152/ajpcell.00462.2010) for interpretation of microscopy colocalization.

## Video display and timing

The selected ROI is a single fixed native-pixel rectangle used for every frame. ROI-reference frame, inclusive clip interval and time zero are independent. No tracking, registration, Z projection or synthetic intermediate observation is applied.

For each enabled channel, low/high limits, gamma and colour remain fixed over the clip. Raw data are not modified. Channel-specific acquisition timestamps and the timing source are retained. Timestamp and scale-bar annotations occupy a separate footer; odd dimensions are padded for the encoder rather than cropped.

Each selected native time point contributes to the timing plan. Constant-frame-rate MP4 repeats native images to approximate irregular intervals. Requested speed is reduced when necessary to avoid skipping a source time point. GIF timing is quantized in 10-ms units; identical neighboring encoded images may merge while retaining their duration. The final native frame uses the median selected native interval as its documented dwell time. Encoders and players may introduce additional practical timing limits; recorded frame maps remain the reference.

MP4 is a lossy H.264 display output. GIF is palette limited. Neither should replace original intensity data in a new measurement. A requested maximum side may downsize output, but the program does not upsample to claim higher resolution.

## Resource and interpretation limits

ND2 time points can be read incrementally, but a 3D job assembles selected channel volumes and masks in memory. Temporary video PNGs also require disk space. Dense marching-cubes meshes can exceed browser or workstation memory; no universal maximum file size is asserted.

The program does not automatically define cells, nuclei or droplets, fit FRAP recovery, estimate absolute molecular concentrations, choose a biologically justified threshold, correct spectral bleed-through, or establish independent biological replication. Those questions need additional experimental information and methods.

OME metadata interpretation follows the [OME-TIFF specification](https://ome-model.readthedocs.io/en/stable/ome-tiff/specification.html). Record the actual software version, source identity, calibration and configuration when using an output in a report.
