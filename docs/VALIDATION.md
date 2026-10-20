# Validation scope

## Included numerical evidence

The original processing core and browser assets were exercised during the NucleArk project. The source snapshot's [validation summary](../validation/VALIDATION_SUMMARY.json) records the tested versions and scope. It is a historical record of those checks, rather than proof of universal compatibility.

The ten portable numerical and synthetic end-to-end cases cover:

- Directional and pooled overlap numerators/denominators, strict threshold equality and undefined zero-signal ratios.
- Displayed points corresponding to acquired qualifying pixels.
- Surface interpolation at known nonuniform Z positions.
- Irregular timestamps, independent time zero, speed reduction and encoder timing quantization.
- Preservation/padding of odd native ROI sizes and fixed display mappings without changing input arrays.
- OME axis/unit handling, rejection of ambiguous TIFF axes, native backups and synthetic GIF/3D exports.

The public release additionally tests its package allowlist and checksum manifest. Run all current tests with:

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

## Real-input and interactive checks

Previous project validation used three real ND2 recordings. Checks compared random-access reads with complete decode, verified native backups and point coordinates, independently recomputed all three overlap percentages, decoded exported videos and tested ROI/time-zero independence. Browser review covered file selection, local paths, ROI editing, interval controls, channel-opacity changes, acquired slices and standalone viewer operation.

Those biological source recordings and private acquisition/result paths are excluded from this repository. The included OME-TIFFs and preview GIF are explicitly synthetic and may be redistributed as demonstrations. They are not biological replicates or measurement standards.

## Public release checks

The repository uses GitHub Actions for the portable suite on Python 3.12 under Windows and Linux, plus release-package construction. Consult the actual check run for the relevant commit. CI on synthetic inputs does not replace interactive browser review or testing an unfamiliar microscope format.

The public-release preparation also checks that the pinned primary package versions exist on public PyPI and that repository files exclude raw ND2 acquisitions, local service sessions and workspace exports. A freshly installed environment passed the fourteen portable cases and three local real-ND2 first-frame comparisons, covering two Z stacks and one time series. These additional source images remain private; only a format-check summary is distributed. The current release report is [validation/RELEASE_VALIDATION.json](../validation/RELEASE_VALIDATION.json).

## What has not been established

There is no independent laboratory validation or measured external community adoption yet. The program has not been benchmarked for every ND2 acquisition mode, every OME-TIFF producer, arbitrary file size, quantitative segmentation accuracy or calibrated biological effect estimation. The interactive interface is currently Chinese; English documentation is supplied.

Source fingerprints, saved settings and tests make the implementation inspectable and reproducible for the stated cases. They do not certify an experimental design or turn display changes into new measured information.
