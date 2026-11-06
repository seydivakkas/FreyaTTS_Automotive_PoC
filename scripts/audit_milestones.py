"""Inspect archive lineage without executing archive code or modifying sources."""

import hashlib
import json
import zipfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    bundles = []
    for path in sorted(Path("M0-M11").glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            entries = {
                name.split("/", 1)[1]: digest(archive.read(name))
                for name in archive.namelist()
                if "/" in name and not name.endswith("/")
            }
        bundles.append((path, entries))
    newest = bundles[-1][1]
    report = {"comparison_basis": bundles[-1][0].name, "archives": []}
    for path, entries in bundles:
        report["archives"].append(
            {
                "name": path.name,
                "sha256": digest(path.read_bytes()),
                "files": len(entries),
                "missing_source_paths_in_M11": [
                    n for n in entries if n.startswith("src/") and n not in newest
                ],
                "changed_source_paths_in_M11": [
                    n
                    for n in entries
                    if n.startswith("src/") and n in newest and entries[n] != newest[n]
                ],
            }
        )
    manifest = json.loads(
        Path("docs/milestones/import-manifest.json").read_text(encoding="utf8")
    )
    report["host_adaptations"] = [
        {
            "path": f["path"],
            "original_sha256": f["sha256"],
            "current_sha256": digest(Path(f["path"]).read_bytes()),
        }
        for f in manifest["files"]
        if Path(f["path"]).is_file()
        and digest(Path(f["path"]).read_bytes()) != f["sha256"]
    ]
    Path("docs/milestones/archive-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("Archive lineage and host adaptations recorded; source archives unchanged.")


if __name__ == "__main__":
    main()
