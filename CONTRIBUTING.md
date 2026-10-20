# Contributing

Bug reports, reproducible examples, documentation improvements and reviewed changes are welcome from iGEM teams and other users.

For a problem report, include the tool version, operating system, Python/package versions, input format and dimension names, relevant settings, the expected behavior and the actual error. A small synthetic example is preferred. Do not post service tokens or private microscopy data; a result's provenance may contain local paths.

For code changes:

1. Create a branch and describe the observed problem or intended behavior.
2. Preserve the distinction between native measurements and display transforms.
3. Add a meaningful numerical, geometry, timing or export regression case when changing those behaviors.
4. Run `python -m unittest discover -s tests -p "test_*.py" -v` and `python package_release.py`.
5. Document changed processing definitions or input support. Do not broaden validation claims without evidence.

Dependency upgrades should retain a recorded test environment and independently check the synthetic reference values. The core should remain usable without a cloud account or online image upload.
