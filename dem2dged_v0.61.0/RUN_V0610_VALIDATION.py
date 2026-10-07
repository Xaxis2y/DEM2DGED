#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.61.0
"""Run the v0.61.0 validation and packaging gate in a dedicated conda env.

This runner does not install packages and never modifies the preserved
dem2dged_v0.59.0 release. It records every command, output, return code and
artifact check in validation_logs so the resulting log can be reviewed as the
release evidence.

Run from Anaconda Prompt after activating a dedicated environment, for example:

    conda activate DEM2DGED060
    python RUN_V0610_VALIDATION.py
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile


VERSION = "0.61.0"
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "validation_logs"


def configure_conda_runtime() -> None:
    """Make GDAL command-line tools and native DLLs discoverable.

    The runner is intentionally usable from an Anaconda Prompt even when the
    caller forgot to run ``conda activate``. ``sys.prefix`` still identifies
    the selected dedicated environment, so prepend its executable and DLL
    directories before any environment or child-process checks.
    """
    prefix = Path(sys.prefix)
    candidates = [prefix / "Library" / "bin", prefix / "Scripts", prefix / "bin"]
    existing = [str(path) for path in candidates if path.is_dir()]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(existing + ([current] if current else []))
    gdal_data = prefix / "Library" / "share" / "gdal"
    proj_data = prefix / "Library" / "share" / "proj"
    if gdal_data.is_dir():
        os.environ.setdefault("GDAL_DATA", str(gdal_data))
    if proj_data.is_dir():
        os.environ.setdefault("PROJ_LIB", str(proj_data))


class ValidationRunner:
    """Small command runner with console and file logging."""

    def __init__(self) -> None:
        configure_conda_runtime()
        LOG_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / ("v0610_validation_" + stamp + ".log")
        self.log = self.log_path.open("w", encoding="utf-8")
        self.failures = []

    def close(self) -> None:
        self.log.close()

    def write(self, text: str = "") -> None:
        print(text)
        self.log.write(text + "\n")
        self.log.flush()

    def section(self, title: str) -> None:
        self.write("\n" + "=" * 78)
        self.write(title)
        self.write("=" * 78)

    def fail(self, message: str) -> None:
        self.failures.append(message)
        self.write("FAIL: " + message)

    def run(self, args, label: str, allow_failure: bool = False) -> int:
        command = [str(value) for value in args]
        self.write("\nCOMMAND: " + subprocess.list2cmdline(command))
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
        )
        if completed.stdout:
            for line in completed.stdout.rstrip().splitlines():
                self.write("  " + line)
        self.write("RETURN CODE: %d" % completed.returncode)
        if completed.returncode != 0 and not allow_failure:
            self.fail(label + " failed")
        return completed.returncode

    def startup_smoke(self, executable: Path, arguments, label: str,
                      timeout_seconds: int = 15) -> None:
        """Start an executable without allowing a GUI process to hang the gate."""
        command = [str(executable)] + [str(value) for value in arguments]
        self.write("\nCOMMAND: " + subprocess.list2cmdline(command))
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        timed_out = False
        try:
            output, _ = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            process.terminate()
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
            output = (exc.output or "") + (output or "")
        if output:
            for line in output.rstrip().splitlines():
                self.write("  " + line)
        self.write("RETURN CODE: %s%s" % (
            process.returncode, " (startup timeout; process terminated)" if timed_out else ""))
        fatal_markers = ("init.tcl", "ModuleNotFoundError", "Traceback", "Fatal Python error")
        if any(marker in output for marker in fatal_markers):
            self.fail(label + " reported a startup failure")
        elif not timed_out and process.returncode not in (0, 1, 2):
            self.fail(label + " returned unexpected code %s" % process.returncode)

    def check_python_files(self) -> None:
        self.section("1. AST syntax check")
        files = sorted(ROOT.rglob("*.py"))
        ignored = {"build", "dist", "archive_stale", "validation_logs"}
        checked = []
        for path in files:
            if any(part in ignored for part in path.parts):
                continue
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            checked.append(path)
        self.write("AST syntax OK: %d Python files" % len(checked))

    def check_environment(self) -> None:
        self.section("2. Dedicated environment check")
        env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
        self.write("Python executable: " + sys.executable)
        self.write("Python version: " + sys.version.replace("\n", " "))
        self.write("CONDA_DEFAULT_ENV: " + (env_name or "<not set>"))
        if env_name.lower() == "base":
            self.fail("The base conda environment is active; activate a dedicated environment first")
        if not shutil.which("gdalwarp"):
            self.fail("gdalwarp is not on PATH")
        required = ("numpy", "osgeo", "pytest", "PyInstaller")
        for module in required:
            result = subprocess.run(
                [sys.executable, "-c", "import " + module],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            self.write("%s: %s" % (module, "available" if result.returncode == 0 else "MISSING"))
            if result.returncode != 0:
                self.fail("Required module is missing: " + module)

    def check_zip(self) -> None:
        self.section("8. Package content and hash check")
        package_dir = ROOT / "output_packages"
        packages = sorted(package_dir.glob("dem2dged_v0.61.0_win64.zip"))
        if not packages:
            self.fail("Expected v0.61.0 package was not created")
            return
        package = packages[-1]
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        self.write("Package: " + str(package))
        self.write("SHA-256: " + digest)
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
        self.write("ZIP members: %d" % len(names))
        forbidden = [name for name in names if "v0.58.0" in name or "v0.59.0" in name]
        if forbidden:
            self.fail("Package contains stale release names: " + ", ".join(forbidden))
        required = {"dem2dged/README.md"}
        missing = sorted(required.difference(names))
        if missing:
            self.fail("Package is missing required members: " + ", ".join(missing))

    def run_all(self) -> int:
        self.section("DEM2DGED v%s validation gate" % VERSION)
        self.write("Release root: " + str(ROOT))
        self.write("Log file: " + str(self.log_path))
        try:
            self.check_environment()
            self.check_python_files()
            self.section("3. Version consistency")
            self.run([sys.executable, "BUMP_VERSION.py", "--check", VERSION],
                     "version consistency")
            self.section("4. GDAL-free audit")
            self.run([sys.executable, "audit_pure.py"], "audit_pure.py")
            self.section("5. Full pytest suite")
            self.run([sys.executable, "-m", "pytest", "-q"], "pytest suite")
            self.section("6. Ground-truth and toolbox checks")
            self.run([sys.executable, "verify_mountain_terrain_v0.59.0.py"],
                     "ground-truth resampler sweep")
            self.run([sys.executable, "DGED_Loader/test_dged_loader.py"],
                     "offline ArcGIS toolbox harness")
            self.section("7. Version resources and PyInstaller build")
            self.run([sys.executable, "make_version_info.py", "gui"],
                     "GUI version resource")
            self.run([sys.executable, "make_version_info.py", "validate"],
                     "validator version resource")
            self.run([sys.executable, "BUILD_AND_PACKAGE.py"],
                     "GUI build and package")
            self.run([sys.executable, "-m", "PyInstaller",
                      "dem2dged_validate.spec", "--noconfirm"],
                     "validator executable build")
            self.section("8. Executable startup smoke checks")
            gui_exe = ROOT / "dist" / "dem2dged.exe"
            validator_exe = ROOT / "dist" / "dem2dged_validate.exe"
            if not gui_exe.exists():
                self.fail("GUI executable is missing after build")
            else:
                self.startup_smoke(gui_exe, ["--version"], "GUI executable startup")
            if not validator_exe.exists():
                self.fail("Validator executable is missing after build")
            else:
                self.run([str(validator_exe), "--help"],
                         "validator executable startup")
            self.check_zip()
        except Exception as exc:
            self.fail("Validation runner exception: %s" % exc)
        finally:
            self.section("FINAL RESULT")
            if self.failures:
                self.write("FAILURES: %d" % len(self.failures))
                for failure in self.failures:
                    self.write("- " + failure)
                self.write("Review the complete log: " + str(self.log_path))
            else:
                self.write("PASS: all v0.61.0 validation-gate steps completed")
                self.write("Review the complete log: " + str(self.log_path))
        return 1 if self.failures else 0


def main() -> int:
    runner = ValidationRunner()
    try:
        return runner.run_all()
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
