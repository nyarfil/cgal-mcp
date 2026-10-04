"""Fetch and safely unpack the pinned CGAL Master catalog inputs.

The catalog is deliberately generated from release artifacts, not from the
existing curated header index.  This script keeps those inputs below ``work/``
so they never become a repository dependency or a tracked source of truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath


VERSION = "6.2.1"
RELEASE_BASE_URL = "https://github.com/CGAL/cgal/releases/download/v6.2.1"
ARTIFACTS = {
    "source": {
        "filename": "CGAL-6.2.1.tar.xz",
        "sha256": "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf",
        "directory": "CGAL-6.2.1",
    },
    "docs": {
        "filename": "CGAL-6.2.1-doc_html.tar.xz",
        "sha256": "805127da33223e32837adcdc00e75faac1f6e8c93bace90cea0ef69f09ca23bb",
        "directory": "doc_html",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(destination: Path, member_name: str) -> Path:
    """Reject archive names that can leave *destination* on any platform."""
    name = PurePosixPath(member_name)
    if not member_name or name.is_absolute() or "\\" in member_name or ".." in name.parts:
        raise ValueError(f"unsafe tar member path: {member_name!r}")
    candidate = (destination / Path(*name.parts)).resolve()
    try:
        candidate.relative_to(destination.resolve())
    except ValueError as error:
        raise ValueError(f"tar member escapes destination: {member_name!r}") from error
    return candidate


def _member_records(archive: Path) -> list[dict[str, object]]:
    """Hash every permitted archive member before it is trusted or extracted."""
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    with tarfile.open(archive, mode="r:xz") as tar:
        for member in tar.getmembers():
            _safe_member_path(Path("."), member.name)
            if member.name in seen:
                raise ValueError(f"duplicate tar member path: {member.name!r}")
            seen.add(member.name)
            if member.isdir():
                member_type = "directory"
                member_sha256 = hashlib.sha256(b"").hexdigest()
            elif member.isfile():
                member_type = "file"
                digest = hashlib.sha256()
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError(f"cannot read tar member: {member.name!r}")
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                member_sha256 = digest.hexdigest()
            else:
                raise ValueError(f"refusing non-regular tar member: {member.name!r}")
            records.append({"path": member.name, "type": member_type, "size": member.size, "sha256": member_sha256})
    return records


def _tree_sha256(records: list[dict[str, object]]) -> str:
    return hashlib.sha256(json.dumps(records, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


def archive_receipt(archive: Path, kind: str, metadata: dict[str, str]) -> dict[str, object]:
    """Return reproducible evidence that an archive and its declared root agree."""
    records = _member_records(archive)
    root = metadata["directory"]
    if not records or any(PurePosixPath(str(record["path"])).parts[0] != root for record in records):
        raise ValueError(f"archive members do not all belong to declared root {root!r}")
    return {
        "schema_version": 1,
        "kind": kind,
        "archive": {"filename": metadata["filename"], "sha256": sha256_file(archive)},
        "root": root,
        "members": records,
        "tree_sha256": _tree_sha256(records),
    }


def _checked_remove_tree(target: Path, root: Path) -> None:
    """Remove only a temporary staging directory below the explicit baseline root."""
    resolved_target = target.resolve()
    resolved_root = root.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"refusing cleanup outside baseline root: {target}") from error
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def _canonical_json_bytes(data: dict[str, object]) -> bytes:
    """Canonical receipt encoding, independent of host newline translation."""
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write_json(destination: Path, data: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent, suffix=".json")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(_canonical_json_bytes(data))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def verify_extracted_tree(extraction_parent: Path, receipt: dict[str, object]) -> None:
    """Compare every receipt member to disk and reject missing, changed, or added files."""
    root_name = receipt.get("root")
    members = receipt.get("members")
    if not isinstance(root_name, str) or not isinstance(members, list):
        raise ValueError("invalid extraction receipt")
    root = extraction_parent / root_name
    if not root.is_dir():
        raise ValueError(f"extracted root missing: {root}")
    expected: dict[str, dict[str, object]] = {}
    for raw_record in members:
        if not isinstance(raw_record, dict):
            raise ValueError("invalid receipt member")
        path = raw_record.get("path")
        if not isinstance(path, str) or PurePosixPath(path).parts[0] != root_name:
            raise ValueError("receipt member is outside declared root")
        expected[path] = raw_record
        disk_path = extraction_parent / Path(*PurePosixPath(path).parts)
        member_type = raw_record.get("type")
        if member_type == "directory":
            if not disk_path.is_dir() or disk_path.is_symlink():
                raise ValueError(f"extracted directory mismatch: {path}")
        elif member_type == "file":
            if not disk_path.is_file() or disk_path.is_symlink():
                raise ValueError(f"extracted file missing or unsafe: {path}")
            if disk_path.stat().st_size != raw_record.get("size") or sha256_file(disk_path) != raw_record.get("sha256"):
                raise ValueError(f"extracted file digest mismatch: {path}")
        else:
            raise ValueError(f"invalid receipt member type: {member_type!r}")
    for disk_path in root.rglob("*"):
        relative = f"{root_name}/{disk_path.relative_to(root).as_posix()}"
        if relative not in expected or disk_path.is_symlink():
            raise ValueError(f"unexpected or unsafe extracted path: {relative}")


def verify_receipt(archive: Path, extraction_parent: Path, receipt: dict[str, object]) -> None:
    """Cryptographically bind a receipt to both its archive and extracted tree."""
    archive_info = receipt.get("archive")
    if not isinstance(archive_info, dict) or archive_info.get("sha256") != sha256_file(archive):
        raise ValueError("archive digest does not match extraction receipt")
    rebuilt = archive_receipt(archive, str(receipt.get("kind")), {
        "filename": str(archive_info.get("filename")), "directory": str(receipt.get("root")),
    })
    if rebuilt != receipt:
        raise ValueError("archive members do not match extraction receipt")
    verify_extracted_tree(extraction_parent, receipt)


def safe_extract_tar_xz(archive: Path, destination: Path) -> None:
    """Extract regular files/directories only, refusing traversal and all links."""
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty extraction directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    _member_records(archive)
    with tarfile.open(archive, mode="r:xz") as tar:
        members = tar.getmembers()
        for member in members:
            _safe_member_path(destination, member.name)
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"refusing non-regular tar member: {member.name!r}")
        # Python 3.12+ additionally applies its standard data filter.  Python
        # 3.10 lacks that argument, but the explicit checks above remain.
        if sys.version_info >= (3, 12):
            tar.extractall(destination, members=members, filter="data")
        else:
            tar.extractall(destination, members=members)


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256_file(destination) == expected_sha256:
        return
    descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent)
    os.close(descriptor)
    temp_path = Path(temporary_name)
    try:
        with urllib.request.urlopen(url) as response, temp_path.open("wb") as temporary:
            shutil.copyfileobj(response, temporary)
        actual_sha256 = sha256_file(temp_path)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual_sha256}"
            )
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _load_receipt(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid extraction receipt: {path}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid extraction receipt: {path}")
    return loaded


def _receipt_projection(receipt: dict[str, object]) -> dict[str, object]:
    archive = receipt["archive"]
    assert isinstance(archive, dict)
    members = receipt["members"]
    assert isinstance(members, list)
    return {
        "filename": archive["filename"], "sha256": archive["sha256"], "root": receipt["root"],
        "member_count": len(members), "tree_sha256": receipt["tree_sha256"],
        "receipt_sha256": hashlib.sha256(_canonical_json_bytes(receipt)).hexdigest(),
        "receipt_sha256_encoding": "sorted-json-indent2-utf8-lf",
    }


def verified_official_provenance(source_root: Path, docs_root: Path) -> dict[str, object]:
    """Require receipts and actual archive/tree verification before production harvest."""
    baseline_root = source_root.parent.parent
    if docs_root.parent.parent != baseline_root:
        raise ValueError("source and docs roots must share one master-baseline root")
    inputs: dict[str, object] = {}
    for kind, extracted_root in (("source", source_root), ("docs", docs_root)):
        metadata = ARTIFACTS[kind]
        if extracted_root.name != metadata["directory"]:
            raise ValueError(f"wrong {kind} extraction root: {extracted_root}")
        archive = baseline_root / "archives" / metadata["filename"]
        receipt_path = extracted_root.parent / "receipt.json"
        receipt = _load_receipt(receipt_path)
        if sha256_file(archive) != metadata["sha256"]:
            raise ValueError(f"official {kind} archive digest mismatch")
        if receipt.get("kind") != kind or receipt.get("root") != metadata["directory"]:
            raise ValueError(f"official {kind} receipt metadata mismatch")
        verify_receipt(archive, extracted_root.parent, receipt)
        inputs[kind] = _receipt_projection(receipt)
    return {"mode": "official", "source": inputs["source"], "docs": inputs["docs"]}


def fetch_baseline(root: Path, source_only: bool = False) -> dict[str, Path]:
    """Download and extract the two signed-off release inputs idempotently."""
    result: dict[str, Path] = {}
    artifacts = (("source", ARTIFACTS["source"]),) if source_only else ARTIFACTS.items()
    for kind, metadata in artifacts:
        archive = root / "archives" / metadata["filename"]
        target_parent = root / kind
        target = target_parent / metadata["directory"]
        download_verified(f"{RELEASE_BASE_URL}/{metadata['filename']}", archive, metadata["sha256"])
        receipt_path = target_parent / "receipt.json"
        receipt = archive_receipt(archive, kind, metadata)
        if target.exists():
            if receipt_path.exists():
                existing = _load_receipt(receipt_path)
                if existing != receipt:
                    raise ValueError(f"existing {kind} receipt does not match verified archive")
                verify_extracted_tree(target_parent, existing)
            else:
                # A pre-receipt baseline is only adopted after byte-for-byte
                # validation against the verified archive.
                verify_extracted_tree(target_parent, receipt)
                _atomic_write_json(receipt_path, receipt)
        else:
            if target_parent.exists() and any(target_parent.iterdir()):
                raise FileExistsError(f"refusing to publish into non-empty extraction parent: {target_parent}")
            if target_parent.exists():
                target_parent.rmdir()
            staging = Path(tempfile.mkdtemp(prefix=f".{kind}-staging-", dir=root))
            try:
                safe_extract_tar_xz(archive, staging)
                verify_extracted_tree(staging, receipt)
                os.replace(staging, target_parent)
                _atomic_write_json(receipt_path, receipt)
            finally:
                if staging.exists():
                    _checked_remove_tree(staging, root)
        result[kind] = target
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "work" / "master-baseline",
        help="ignored directory for archives and extracted release inputs",
    )
    parser.add_argument("--source-only", action="store_true", help="download/extract only the source release")
    arguments = parser.parse_args()
    inputs = fetch_baseline(arguments.root, source_only=arguments.source_only)
    for kind, path in inputs.items():
        print(f"{kind}={path.resolve()}")


if __name__ == "__main__":
    main()
