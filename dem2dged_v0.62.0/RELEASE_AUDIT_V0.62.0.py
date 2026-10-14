#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
"""Read-only release ZIP audit for DEM2DGED (version: see VERSION below)."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path


VERSION = "0.62.0"
ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "output_packages" / f"dem2dged_v{VERSION}_win64.zip"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if not PACKAGE.is_file():
        raise SystemExit(f"Missing package: {PACKAGE}")

    required = {
        "dem2dged/dem2dged.exe",
        "dem2dged/VERSION.json",
        "dem2dged/LICENSE",
        "dem2dged/README.md",
        "dem2dged/checksums.sha256",
        "dem2dged/source/dem2dged.py",
        "dem2dged/source/dem2dged_gui.py",
        "dem2dged/source/dem2dged_validate.py",
        "dem2dged/source/dem2dged_compliance.py",
        "dem2dged/source/dem2dged_evidence.py",
        "dem2dged/source/BUILD_AND_PACKAGE.py",
        "dem2dged/source/REQUIREMENTS_COMPLIANCE_V%s.md" % VERSION,
        # v0.61.5: these were silently dropped from the v0.61.3 package.
        "dem2dged/source/DGED_Loader.pyt",
        "dem2dged/source/DGED_Loader/DGED_Loader.pyt",
        "dem2dged/source/QUICKSTART.html",
        # v0.61.6: beginner evidence-gate help.
        "dem2dged/EVIDENCE_GATE_BEGINNER_GUIDE.md",
        "dem2dged/EVIDENCE_GATE_BEGINNER_GUIDE.html",
        "dem2dged/source/dem2dged_help.py",
        "dem2dged/source/dem2dged_reference.py",
        "dem2dged/source/reference_catalog.json",
    }

    with zipfile.ZipFile(PACKAGE) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise SystemExit(f"ZIP CRC failure: {bad_member}")

        names = archive.namelist()
        normalized = {name.replace("\\", "/") for name in names}
        roots = {name.split("/", 1)[0] for name in normalized if name}
        if roots != {"dem2dged"}:
            raise SystemExit(f"Unexpected ZIP roots: {sorted(roots)}")

        missing = sorted(required.difference(normalized))
        if missing:
            raise SystemExit("Missing required members: " + ", ".join(missing))

        forbidden = sorted(
            name for name in normalized
            if "/.pytest" in name or name.lower().endswith("_log.txt") or
            name.lower().endswith(".pyc") or "/__pycache__/" in name
        )
        if forbidden:
            raise SystemExit("Generated artifacts found: " + ", ".join(forbidden[:20]))

        by_normalized = {name.replace("\\", "/"): name for name in names}
        version_info = json.loads(
            archive.read(by_normalized["dem2dged/VERSION.json"]).decode("utf-8")
        )
        if version_info.get("version") != VERSION:
            raise SystemExit(f"VERSION.json mismatch: {version_info!r}")

        license_text = archive.read(
            by_normalized["dem2dged/LICENSE"]
        ).decode("utf-8", errors="replace")
        if "GNU GENERAL PUBLIC LICENSE" not in license_text:
            raise SystemExit("Packaged LICENSE does not contain the GPL text")

        checksum_text = archive.read(
            by_normalized["dem2dged/checksums.sha256"]
        ).decode("utf-8")
        expected = {}
        for row in checksum_text.splitlines():
            digest, member = row.split("  ", 1)
            expected[member.replace("\\", "/")] = digest

        payload_members = normalized.difference({"dem2dged/checksums.sha256"})
        if set(expected) != payload_members:
            missing_hashes = sorted(payload_members.difference(expected))
            extra_hashes = sorted(set(expected).difference(payload_members))
            raise SystemExit(
                f"Checksum membership mismatch; missing={missing_hashes}, extra={extra_hashes}"
            )
        for normalized_name, expected_digest in expected.items():
            actual = sha256_bytes(archive.read(by_normalized[normalized_name]))
            if actual != expected_digest:
                raise SystemExit(f"Checksum mismatch: {normalized_name}")

    print(f"Package: {PACKAGE}")
    print(f"Version: {VERSION}")
    print(f"Members: {len(names)}")
    print(f"ZIP SHA-256: {sha256_file(PACKAGE)}")
    print("CRC/integrity: PASS")
    print("License/source/checksum membership: PASS")
    print("All packaged payload checksums: PASS")
    print("Generated-artifact exclusion: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

