from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
import unicodedata
import unittest
from urllib.parse import urlsplit


ARTIFACT_URL = "https://github.com/actions/python-versions/releases/download/3.12.10-14343898437/python-3.12.10-linux-24.04-x64.tar.gz"
ARTIFACT_FILENAME = "python-3.12.10-linux-24.04-x64.tar.gz"
ARTIFACT_SIZE = 121612690
ARTIFACT_SHA256 = "b9bd943c5fc9244f796deef42c59d29ab9278d8a718851c67de6b44846320f33"
FINAL_HOST = "release-assets.githubusercontent.com"
ROOT_SENTINEL_RAW_NAME = "."
_DRIVE = re.compile(r"^[A-Za-z]:")
_REDIRECTS = {301, 302, 303, 307, 308}


class InventoryEvidenceError(AssertionError):
    pass


def _has_control(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


def _request(url: str) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise InventoryEvidenceError("unsafe evidence URL")
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=30)
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "hwm-i10-0091-archive-inventory/3",
    }
    # Deliberately no Authorization, Cookie, Proxy-Authorization, or credential-derived headers.
    connection.request("GET", target, headers=headers)
    return connection, connection.getresponse()


def _download_exact(destination: Path) -> dict[str, object]:
    initial = urlsplit(ARTIFACT_URL)
    if initial.hostname != "github.com" or PurePosixPath(initial.path).name != ARTIFACT_FILENAME:
        raise InventoryEvidenceError("initial artifact identity mismatch")

    first_connection, first = _request(ARTIFACT_URL)
    try:
        if first.status not in _REDIRECTS:
            raise InventoryEvidenceError(f"exact URL did not return one redirect: HTTP {first.status}")
        location = first.getheader("Location")
        if not location:
            raise InventoryEvidenceError("redirect omitted Location")
        redirected = urlsplit(location)
        if redirected.scheme != "https" or redirected.hostname != FINAL_HOST:
            raise InventoryEvidenceError(f"unexpected redirect host: {redirected.hostname!r}")
    finally:
        first.read()
        first.close()
        first_connection.close()

    second_connection, second = _request(location)
    try:
        if second.status in _REDIRECTS:
            raise InventoryEvidenceError("artifact acquisition exceeded one redirect")
        if second.status != 200:
            raise InventoryEvidenceError(f"artifact returned HTTP {second.status}")
        declared = second.getheader("Content-Length")
        if declared is None or int(declared) != ARTIFACT_SIZE:
            raise InventoryEvidenceError(f"unexpected Content-Length: {declared!r}")
        digest = hashlib.sha256()
        count = 0
        with destination.open("xb") as stream:
            while True:
                chunk = second.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > ARTIFACT_SIZE:
                    raise InventoryEvidenceError("artifact exceeded exact byte count")
                stream.write(chunk)
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if count != ARTIFACT_SIZE:
            raise InventoryEvidenceError(f"artifact byte count mismatch: {count}")
        if actual_hash != ARTIFACT_SHA256:
            raise InventoryEvidenceError(f"artifact SHA-256 mismatch: {actual_hash}")
        return {
            "artifact_url": ARTIFACT_URL,
            "filename": ARTIFACT_FILENAME,
            "size_bytes": count,
            "sha256": actual_hash,
            "redirect_count": 1,
            "final_host": FINAL_HOST,
            "authorization_header": False,
            "cookies": False,
            "credentials": False,
        }
    finally:
        second.close()
        second_connection.close()


def _validate_text(raw: str, *, context: str) -> None:
    if not raw or raw.startswith("/") or _DRIVE.match(raw) or "\\" in raw or _has_control(raw):
        raise InventoryEvidenceError(f"unsafe {context}: {raw!r}")
    if unicodedata.normalize("NFC", raw) != raw:
        raise InventoryEvidenceError(f"non-NFC {context}: {raw!r}")


def _normalize_member_path(raw: str, *, member_type: str) -> str:
    _validate_text(raw, context="archive member path")
    value = raw
    if value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("./"):
        raise InventoryEvidenceError(f"unsafe archive member transport prefix: {raw!r}")

    # Prefix removal must not reveal an absolute or drive-prefixed path.
    _validate_text(value, context="archive member path after transport normalization")

    if value.endswith("/"):
        if member_type != "directory":
            raise InventoryEvidenceError(f"trailing slash on non-directory archive member: {raw!r}")
        value = value[:-1]
        if not value or value.endswith("/"):
            raise InventoryEvidenceError(f"unsafe repeated directory trailing slash: {raw!r}")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InventoryEvidenceError(f"unsafe archive member segment: {raw!r}")
    return "/".join(parts)


def _normalize_linkname(raw: str) -> str:
    _validate_text(raw, context="archive linkname")
    value = raw
    if value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("./"):
        raise InventoryEvidenceError(f"unsafe archive linkname transport prefix: {raw!r}")
    _validate_text(value, context="archive linkname after transport normalization")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InventoryEvidenceError(f"unsafe archive linkname segment: {raw!r}")
    return "/".join(parts)


def _resolve_symlink_target(path: str, normalized_linkname: str) -> str:
    parent = path.split("/")[:-1]
    target = parent + normalized_linkname.split("/")
    if not target or any(part in {"", ".", ".."} for part in target):
        raise InventoryEvidenceError(f"unsafe resolved symlink target: {path!r} -> {normalized_linkname!r}")
    return "/".join(target)


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "directory"
    if member.isfile():
        return "regular"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    return "special"


def _tar_type(member: tarfile.TarInfo) -> str:
    value = member.type
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def _root_sentinel_record(member: tarfile.TarInfo) -> dict[str, object]:
    if member.name != ROOT_SENTINEL_RAW_NAME:
        raise InventoryEvidenceError(f"root sentinel raw name mismatch: {member.name!r}")
    if not member.isdir():
        raise InventoryEvidenceError(
            f"exact root sentinel is not a directory/archive-root marker: tar_type={_tar_type(member)!r}"
        )
    if member.size != 0:
        raise InventoryEvidenceError(f"exact root sentinel size is not zero: {member.size}")
    if member.issym():
        raise InventoryEvidenceError("exact root sentinel is a symlink")
    if member.islnk():
        raise InventoryEvidenceError("exact root sentinel is a hardlink")
    if member.linkname != "":
        raise InventoryEvidenceError(f"exact root sentinel linkname is not empty: {member.linkname!r}")
    payload_bytes = member.size
    if payload_bytes != 0:
        raise InventoryEvidenceError(f"exact root sentinel contains payload bytes: {payload_bytes}")

    return {
        "raw_name": ROOT_SENTINEL_RAW_NAME,
        "member_type": "archive_root_sentinel",
        "tar_type": _tar_type(member),
        "mode": member.mode,
        "size": 0,
        "linkname": "",
        "normalized_path": None,
        "extract": False,
    }


def _inventory(archive_path: Path) -> tuple[bytes, dict[str, object]]:
    # Artifact identity has already been verified. Read inert tar metadata only.
    # No member is extracted, opened as payload, imported, or executed.
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()

    records: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    root_sentinel: dict[str, object] | None = None
    root_sentinel_count = 0

    for member in members:
        if member.name == ROOT_SENTINEL_RAW_NAME:
            root_sentinel_count += 1
            if root_sentinel_count != 1:
                raise InventoryEvidenceError(
                    f"exact root sentinel appears more than once: count={root_sentinel_count}"
                )
            root_sentinel = _root_sentinel_record(member)
            continue

        member_type = _member_type(member)
        path = _normalize_member_path(member.name, member_type=member_type)
        previous_raw = seen.get(path)
        if previous_raw is not None:
            raise InventoryEvidenceError(
                f"duplicate canonical archive path: {path!r} from {previous_raw!r} and {member.name!r}"
            )
        seen[path] = member.name

        record: dict[str, object] = {
            "raw_name": member.name,
            "normalized_path": path,
            "member_type": member_type,
            "tar_type": _tar_type(member),
            "mode": member.mode,
            "size": member.size,
            "linkname": member.linkname,
            "extract": member_type in {"directory", "regular", "symlink", "hardlink"},
        }

        if member_type in {"symlink", "hardlink"}:
            normalized_linkname = _normalize_linkname(member.linkname)
            if member_type == "symlink":
                resolved = _resolve_symlink_target(path, normalized_linkname)
            else:
                # Owner-authorized tar hardlink semantics: linkname addresses archive root.
                resolved = normalized_linkname
            record["normalized_linkname"] = normalized_linkname
            record["resolved_target"] = resolved
        records.append(record)

    if root_sentinel_count != 1 or root_sentinel is None:
        raise InventoryEvidenceError(
            f"exact archive must contain exactly one root sentinel: count={root_sentinel_count}"
        )

    records.sort(
        key=lambda item: (
            str(item["normalized_path"]),
            str(item["member_type"]),
            str(item["raw_name"]),
        )
    )
    by_path = {str(item["normalized_path"]): item for item in records}

    def terminal(path: str, stack: tuple[str, ...] = ()) -> tuple[str, str]:
        if path not in by_path:
            raise InventoryEvidenceError(f"dangling archive link target: {path!r}")
        if path in stack:
            raise InventoryEvidenceError("archive link cycle: " + " -> ".join(stack + (path,)))
        item = by_path[path]
        item_type = str(item["member_type"])
        if item_type in {"symlink", "hardlink"}:
            return terminal(str(item["resolved_target"]), stack + (path,))
        if item_type == "special":
            raise InventoryEvidenceError(f"archive link resolves to special member: {path!r}")
        if item_type not in {"regular", "directory"}:
            raise InventoryEvidenceError(f"archive link has unsupported terminal type: {path!r} -> {item_type!r}")
        return path, item_type

    symlinks: list[dict[str, object]] = []
    hardlinks: list[dict[str, object]] = []
    specials: list[dict[str, object]] = []
    for item in records:
        item_type = str(item["member_type"])
        if item_type == "symlink":
            terminal_path, terminal_type = terminal(str(item["normalized_path"]))
            allowed = dict(item)
            allowed["terminal_target"] = terminal_path
            allowed["terminal_target_type"] = terminal_type
            symlinks.append(allowed)
        elif item_type == "hardlink":
            terminal_path, terminal_type = terminal(str(item["normalized_path"]))
            allowed = dict(item)
            allowed["terminal_target"] = terminal_path
            allowed["terminal_target_type"] = terminal_type
            hardlinks.append(allowed)
        elif item_type == "special":
            specials.append(dict(item))

    canonical_records: list[dict[str, object]] = [root_sentinel, *records]
    canonical = json.dumps(
        canonical_records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    summary: dict[str, object] = {
        "root_sentinel": root_sentinel,
        "total_member_count": len(canonical_records),
        "archive_root_sentinel_count": root_sentinel_count,
        "directory_count": sum(item["member_type"] == "directory" for item in records),
        "regular_count": sum(item["member_type"] == "regular" for item in records),
        "symlink_count": len(symlinks),
        "hardlink_count": len(hardlinks),
        "special_count": len(specials),
        "symlinks": symlinks,
        "hardlinks": hardlinks,
        "specials": specials,
        "raw_to_normalized": [
            {
                "raw_name": item["raw_name"],
                "normalized_path": item["normalized_path"],
            }
            for item in records
        ],
        "canonical_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    return canonical, summary


class ExactPinnedArchiveInventoryEvidence(unittest.TestCase):
    def test_owner_authorized_transport_normalization_examples(self) -> None:
        self.assertEqual(
            _normalize_member_path("./setup.sh", member_type="regular"),
            "setup.sh",
        )
        self.assertEqual(
            _normalize_member_path("./bin/", member_type="directory"),
            "bin",
        )
        self.assertEqual(_normalize_linkname("./bin/python3.12"), "bin/python3.12")

        rejected_members = [
            ("./", "directory"),
            ("././foo", "regular"),
            ("foo/./bar", "regular"),
            ("foo/../bar", "regular"),
            (".//x", "regular"),
            ("foo//bar", "regular"),
            ("foo/", "regular"),
            ("foo//", "directory"),
            ("/x", "regular"),
            ("C:/x", "regular"),
            ("./C:/x", "regular"),
            ("foo\\bar", "regular"),
        ]
        for raw, member_type in rejected_members:
            with self.subTest(raw=raw, member_type=member_type):
                with self.assertRaises(InventoryEvidenceError):
                    _normalize_member_path(raw, member_type=member_type)

        rejected_linknames = [
            "",
            "./",
            "././foo",
            "../x",
            "./../x",
            "foo/.",
            "foo/../bar",
            "foo//bar",
            "/x",
            "C:/x",
            "./C:/x",
            "foo\\bar",
        ]
        for raw in rejected_linknames:
            with self.subTest(linkname=raw):
                with self.assertRaises(InventoryEvidenceError):
                    _normalize_linkname(raw)

    def test_exact_pinned_archive_header_inventory_only(self) -> None:
        self.assertEqual(os.environ.get("GITHUB_ACTIONS"), "true")
        with tempfile.TemporaryDirectory(prefix="i10-0091-inventory-") as temporary:
            archive_path = Path(temporary) / ARTIFACT_FILENAME
            identity = _download_exact(archive_path)
            canonical, summary = _inventory(archive_path)
            print("I10-0091 ARTIFACT_IDENTITY " + json.dumps(identity, sort_keys=True, separators=(",", ":")))
            print(
                "I10-0091 ROOT_SENTINEL "
                + json.dumps(summary["root_sentinel"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            print(
                "I10-0091 CANONICAL_INVENTORY "
                + json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            print("I10-0091 CANONICAL_BYTES " + str(len(canonical)))

            self.assertEqual(summary["archive_root_sentinel_count"], 1)
            self.assertFalse(
                summary["specials"],
                "special archive members are forbidden: "
                + json.dumps(summary["specials"], ensure_ascii=False, sort_keys=True),
            )


if __name__ == "__main__":
    unittest.main()
