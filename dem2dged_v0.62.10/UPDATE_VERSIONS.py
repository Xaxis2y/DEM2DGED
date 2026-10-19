#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.58.1
#
# UPDATE_VERSIONS.py -- RETIRED. Use BUMP_VERSION.py instead.
#
# WHY THIS FILE NO LONGER DOES ANYTHING
# -------------------------------------
# Up to v0.58.0 this script did two things, both unsafe to repeat:
#
#   1. It PREPENDED a HARDCODED "Changes in 0.57.1" block to VERSION.txt.
#      There was no guard against the block already being there, so running
#      the script a second time silently produced a VERSION.txt with the same
#      changelog section twice -- and the text it inserted was frozen at
#      v0.57.1, so on any later release it would have prepended a stale,
#      factually wrong section describing a different release.
#
#   2. It REBUILT VALIDATOR_VERSION.txt's header from a hardcoded
#      VERSION_DISPLAY = "0.57.1" and re-stamped the build date, which would
#      have silently rolled the validator version BACKWARDS on any release
#      after v0.57.1.
#
# Neither behaviour is recoverable from by re-running the script, and neither
# had a dry-run mode. It is kept as this guard rather than deleted so that an
# old note, build script or shell history entry that still calls it fails
# loudly with the correct instruction instead of corrupting the release notes.
#
# WHAT TO USE INSTEAD
# -------------------
#   conda activate DGED
#   python BUMP_VERSION.py --from 0.58.1 --to 0.59.0            :: dry run
#   python BUMP_VERSION.py --from 0.58.1 --to 0.59.0 --apply    :: write
#   python BUMP_VERSION.py --check 0.59.0                       :: audit
#
# BUMP_VERSION.py is generic (no hardcoded version), idempotent (it only
# rewrites OLD -> NEW, so a second run is a no-op), dry-run by default, and it
# deliberately does NOT write changelog prose: add the new "Changes in vX.Y.Z"
# section to VERSION.txt, VALIDATOR_VERSION.txt and DGED_Loader/VERSION.txt by
# hand, then confirm with --check.

import sys

MESSAGE = """\
UPDATE_VERSIONS.py is retired and does nothing.

It prepended a hardcoded v0.57.1 changelog block to VERSION.txt with no
idempotence guard, and rebuilt VALIDATOR_VERSION.txt's header from a
hardcoded 0.57.1, so running it on any later release corrupted the release
notes.

Use BUMP_VERSION.py instead:

    python BUMP_VERSION.py --from <old> --to <new>           (dry run)
    python BUMP_VERSION.py --from <old> --to <new> --apply   (write)
    python BUMP_VERSION.py --check <version>                 (audit only)

Changelog prose is written by hand, on purpose.
"""


def main():
    sys.stderr.write(MESSAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
