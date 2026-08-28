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
        "User-Agent": "hwm-i10-0091-archive-inventory/1",
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


def _normalize_member_path(raw: str) -> str:
    if not raw or raw.startswith("/") or _DRIVE.match(raw) or "\\" in raw or _has_control(raw):
        raise InventoryEvidenceError(f"unsafe archive member path: {raw!r}")
    if unicodedata.normalize("NFC", raw) != raw:
        raise InventoryEvidenceError(f"non-NFC archive member path: {raw!r}")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InventoryEvidenceError(f"unsafe archive member segment: {raw!r}")
    return "/".join(parts)


def _validate_linkname(raw: str) -> None:
    if not raw or raw.startswith("/") or _DRIVE.match(raw) or "\\" in raw or _has_control(raw):
        raise InventoryEvidenceError(f"unsafe archive linkname: {raw!r}")
    if unicodedata.normalize("NFC", raw) != raw:
        raise InventoryEvidenceError(f"non-NFC archive linkname: {raw!r}")


def _lexical(parts: list[str]) -> str:
    resolved: list[str] = []
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved:
                raise InventoryEvidenceError("archive link target escapes extraction root")
            resolved.pop()
        else:
            resolved.append(part)
    if not resolved:
        raise InventoryEvidenceError("archive link target resolves to extraction root, not an exact member")
    return "/".join(resolved)


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "directory"
    if member.isfile():
        return "regular"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    return "other"


def _inventory(archive_path: Path) -> tuple[bytes, dict[str, object]]:
    # Artifact identity has already been verified. This function reads tar headers only.
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()

    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for member in members:
        path = _normalize_member_path(member.name)
        if path in seen:
            raise InventoryEvidenceError(f"duplicate normalized archive path: {path!r}")
        seen.add(path)
        member_type = _member_type(member)
        record: dict[str, object] = {
            "path": path,
            "type": member_type,
            "mode": member.mode,
            "size": member.size,
        }
        if member_type in {"symlink", "hardlink"}:
            _validate_linkname(member.linkname)
            if member_type == "symlink":
                resolved = _lexical(path.split("/")[:-1] + member.linkname.split("/"))
            else:
                # POSIX tar hardlink linkname names a member from the archive namespace root.
                resolved = _lexical(member.linkname.split("/"))
            record["linkname"] = member.linkname
            record["resolved_target"] = resolved
        records.append(record)

    records.sort(key=lambda item: (str(item["path"]), str(item["type"])))
    by_path = {str(item["path"]): item for item in records}

    def terminal(path: str, stack: tuple[str, ...] = ()) -> tuple[str, str]:
        if path not in by_path:
            raise InventoryEvidenceError(f"dangling archive link target: {path!r}")
        if path in stack:
            raise InventoryEvidenceError("archive link cycle: " + " -> ".join(stack + (path,)))
        item = by_path[path]
        item_type = str(item["type"])
        if item_type == "symlink":
            return terminal(str(item["resolved_target"]), stack + (path,))
        if item_type == "hardlink":
            target = by_path.get(str(item["resolved_target"]))
            if target is None or target["type"] != "regular":
                raise InventoryEvidenceError(f"hardlink target is not an exact regular member: {path!r}")
            return str(target["path"]), "regular"
        if item_type == "other":
            raise InventoryEvidenceError(f"archive link resolves to special member: {path!r}")
        return path, item_type

    symlinks: list[dict[str, object]] = []
    hardlinks: list[dict[str, object]] = []
    specials: list[dict[str, object]] = []
    for item in records:
        item_type = str(item["type"])
        if item_type == "symlink":
            terminal_path, terminal_type = terminal(str(item["path"]))
            allowed = dict(item)
            allowed["terminal_target"] = terminal_path
            allowed["terminal_target_type"] = terminal_type
            symlinks.append(allowed)
        elif item_type == "hardlink":
            target = by_path.get(str(item["resolved_target"]))
            if target is None or target["type"] != "regular":
                raise InventoryEvidenceError(f"hardlink target is not an exact regular member: {item!r}")
            allowed = dict(item)
            allowed["terminal_target"] = str(target["path"])
            allowed["terminal_target_type"] = "regular"
            hardlinks.append(allowed)
        elif item_type == "other":
            specials.append(dict(item))

    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    counts = {kind: sum(item["type"] == kind for item in records) for kind in ("directory", "regular", "symlink", "hardlink", "other")}
    summary: dict[str, object] = {
        "member_count": len(records),
        "counts": counts,
        "canonical_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
        "symlinks": symlinks,
        "hardlinks": hardlinks,
        "specials": specials,
    }
    if specials:
        raise InventoryEvidenceError("special archive members are forbidden: " + json.dumps(specials, sort_keys=True))
    return canonical, summary


class ExactPinnedArchiveInventoryEvidence(unittest.TestCase):
    def test_exact_pinned_archive_header_inventory_only(self) -> None:
        self.assertEqual(os.environ.get("GITHUB_ACTIONS"), "true")
        with tempfile.TemporaryDirectory(prefix="i10-0091-inventory-") as temporary:
            archive_path = Path(temporary) / ARTIFACT_FILENAME
            identity = _download_exact(archive_path)
            canonical, summary = _inventory(archive_path)
            print("I10-0091 ARTIFACT_IDENTITY " + json.dumps(identity, sort_keys=True, separators=(",", ":")))
            print("I10-0091 CANONICAL_INVENTORY " + json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            print("I10-0091 CANONICAL_BYTES " + str(len(canonical)))
            self.assertFalse(summary["specials"])


if __name__ == "__main__":
    unittest.main()
