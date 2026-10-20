# Output reference

Interactive jobs write new timestamped directories under `workspace/outputs/`. File selection copies an input into `workspace/uploads/`; local-path mode reads it directly. `--data-root` can place workspace files elsewhere.

## Common provenance

| File | Purpose |
| --- | --- |
| `settings.json` | Processing configuration, source hash, channels, calibration, selection, geometry and timing decisions |
| `source.json` | Source filename, original local path, SHA-256, dimensions and metadata |
| `software_versions.json` | Python/library/FFmpeg versions and processing-code fingerprints |
| `METHODS.txt` | A task-specific account of the operations used |
| `manifest.json` | File sizes and SHA-256 checksums |
| `bundle.zip` | Result files; the original ND2 is not included |

Generated provenance may contain absolute paths from the user's own machine. They remain local during processing; review a result folder before distributing it. The repository and release bundle contain synthetic examples only and no project ND2 files or service sessions.

## Three-dimensional jobs

Outputs include `viewer.html`, native OME-TIFF/NPZ arrays, acquired Z-coordinate CSV data, `native_overlap.csv`, native threshold masks, acquired-plane views and PLY surface meshes. The interactive viewer lets users switch between sampled native positions and isosurfaces, adjust per-channel opacity and inspect same-position overlap and original XY slices.

The native backups and saved numerical data are the measurement reference. Rendered points and meshes are inspection aids.

## Time-series jobs

`full.gif`, `full.mp4`, `crop.gif` and `crop.mp4` use the same interval and display mapping. An initial preview exports only the full-field view. A final export includes the selected full field and crop.

| File | Purpose |
| --- | --- |
| `native_frame_timing.csv` | Source frame index, source and relative time, display duration and MP4 repetitions |
| `channel_acquisition_times.csv` | Per-channel native timestamps and their metadata source |
| `clipping_and_saturation.csv` | Native saturation and display clipping counts, kept separate |
| `ROI_reference_overlay.png` | ROI drawn on its chosen reference frame |
| `ROI_native_crop_reference.png` | Unannotated rendered reference crop |
| `full_field_first_frame.png` | Rendered initial full field |
| `*_gif_encoded_timing.csv` | Decoded GIF durations for format-level inspection |

Indices in JSON/CSV are explicitly zero-based where named `*_zero_based`; the browser's frame controls are one-based. Original timestamp precision is retained in numerical files even when display labels are rounded.

Source image arrays are not modified. The output PNGs, GIF and MP4 are mapped display images, not quantitative raw-intensity replacements.
