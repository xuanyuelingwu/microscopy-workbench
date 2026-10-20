"""Release contents are deliberate and never inferred from a whole workspace."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import package_release as release

TEMP=Path(__file__).resolve().parent/"_temp"
TEMP.mkdir(exist_ok=True)


class Distribution(unittest.TestCase):
    def fixture(self,root):
        (root/"app.py").write_text("# fixture\n",encoding="utf-8")
        (root/"core.py").write_text("# fixture\n",encoding="utf-8")
        (root/"examples").mkdir()
        (root/"examples/SYNTHETIC_sample.ome.tif").write_bytes(b"synthetic fixture")

    def test_workspace_credentials_and_raw_data_are_not_collected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root=Path(temp);self.fixture(root)
            (root/"workspace").mkdir()
            (root/"workspace/session.json").write_text("private-session",encoding="utf-8")
            (root/"experiment.nd2").write_bytes(b"private-acquisition")
            (root/".env").write_text("private-value",encoding="utf-8")
            paths={p.relative_to(root).as_posix() for p in release.collect_files(root)}
            self.assertEqual(paths,{"app.py","core.py","examples/SYNTHETIC_sample.ome.tif"})

    def test_unexpected_acquisition_inside_examples_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root=Path(temp);self.fixture(root)
            (root/"examples/experimental.nd2").write_bytes(b"private")
            with self.assertRaises(ValueError):release.collect_files(root)

    def test_unmarked_tiff_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root=Path(temp);self.fixture(root)
            (root/"examples/unlabelled.ome.tif").write_bytes(b"unlabelled")
            with self.assertRaises(ValueError):release.collect_files(root)

    def test_manifest_matches_every_archive_member(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root=Path(temp);self.fixture(root)
            archive,manifest=release.build_release(root,root/"dist/release.zip")
            with zipfile.ZipFile(archive) as z:
                saved=json.loads(z.read("microscopy-workbench/RELEASE_MANIFEST.json"))
                self.assertEqual(saved,manifest)
                self.assertEqual(len(z.namelist()),len(manifest["files"])+1)
                for record in manifest["files"]:
                    content=z.read("microscopy-workbench/"+record["path"])
                    self.assertEqual(len(content),record["bytes"])
                    self.assertEqual(hashlib.sha256(content).hexdigest(),record["sha256"])


if __name__=="__main__":unittest.main(verbosity=2)
