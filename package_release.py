"""Build an allowlisted community ZIP without workspace exports or source acquisitions."""
from pathlib import Path
import hashlib
import json
import zipfile
import core

BASE=Path(__file__).resolve().parent
ROOT_FILES=["app.py","core.py","replay.py","generate_demo.py","package_release.py",
            "start.bat","install.bat","requirements.txt","requirements-lock-windows-py312.txt",
            "README.md","README.zh-CN.md","README.txt","README_EN.txt","LICENSE",
            "CITATION.cff","THIRD_PARTY_NOTICES.txt","CONTRIBUTING.md","CHANGELOG.md",
            ".gitignore",".gitattributes",".python-version"]
SAFE_FOLDERS=["static","examples","tests","docs","third_party_licenses"]
SAFE_REPORTS=["validation/VALIDATION_SUMMARY.json","validation/RELEASE_VALIDATION.json"]


def collect_files(base):
    base=Path(base).resolve()
    found={base/n for n in ROOT_FILES+SAFE_REPORTS if (base/n).is_file()}
    for name in SAFE_FOLDERS:
        found.update(p for p in (base/name).rglob("*") if p.is_file())
    result=[]
    for p in sorted(found,key=lambda x:x.relative_to(base).as_posix()):
        relative=p.relative_to(base)
        if any(x in relative.parts for x in ["__pycache__","_temp"]):continue
        if p.is_symlink() or not p.resolve().is_relative_to(base):
            raise ValueError("External or symbolic-link content is not publishable: "+relative.as_posix())
        if p.suffix.lower() in [".nd2",".rar",".zip"] or relative.name in [".env","session.json"]:
            raise ValueError("Unexpected acquisition, archive or session file: "+relative.as_posix())
        if p.suffix.lower() in [".tif",".tiff"] and not (relative.parts[0]=="examples" and p.name.startswith("SYNTHETIC_")):
            raise ValueError("Only explicitly synthetic example TIFFs are publishable: "+relative.as_posix())
        result.append(p)
    return result


def build_release(base=BASE,output=None):
    base=Path(base).resolve()
    files=collect_files(base)
    if not (base/"app.py").is_file() or not (base/"core.py").is_file():
        raise ValueError("The package needs app.py and core.py.")
    out=Path(output) if output else base/"dist"/f"microscopy-workbench-v{core.VERSION}.zip"
    out.parent.mkdir(parents=True,exist_ok=True)
    records=[{"path":p.relative_to(base).as_posix(),"bytes":p.stat().st_size,
              "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    manifest={"version":core.VERSION,"source_data_included":False,
              "synthetic_example_data_included":True,"files":records}
    contents={r["path"]:p.read_bytes() for r,p in zip(records,files)}
    contents["RELEASE_MANIFEST.json"]=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for relative,data in sorted(contents.items()):
            info=zipfile.ZipInfo("microscopy-workbench/"+relative,date_time=(2026,10,20,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            archive.writestr(info,data,compresslevel=6)
    (out.parent/"RELEASE_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent/"SHA256SUMS").write_text(digest+"  "+out.name+"\n",encoding="ascii")
    return out,manifest


if __name__=="__main__":
    output,manifest=build_release()
    print(json.dumps({"archive":str(output),"files":len(manifest["files"]),
                      "experimental_data_included":False},indent=2))
