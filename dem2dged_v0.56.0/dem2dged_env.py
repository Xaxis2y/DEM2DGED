# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.56.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Which Python is actually running this, and is it the activated one?

WHY THIS MODULE EXISTS
----------------------
The same mistake was reported twice in one afternoon, in two different
scripts, and both times the tool's own error message sent the reader the
wrong way:

    (DGED) C:\\...\\dem2dged_v0.41>audit_pure.py
    ModuleNotFoundError: No module named 'numpy'

    (DGED) C:\\...\\dem2dged_v0.41>PACKAGE_v0.44.py
    ERROR: cannot import dem2dged_lib (No module named 'osgeo').
           Are you in the DGED environment?

The prompt says (DGED). numpy and osgeo ARE installed in DGED. Both messages
are wrong, and the second is wrong in the most expensive way -- it asserts
the one thing the operator can see is false, so the natural next step is to
reinstall packages into an environment that was never the problem.

The real cause is the command form. Typed as `script.py` rather than
`python script.py`, Windows resolves the .py file association -- the `py`
launcher, or whatever Python owns .py in the registry -- and runs the script
in a COMPLETELY DIFFERENT interpreter from the activated conda environment.
`conda activate` only changes PATH; it does not touch the file association.
So the prompt still reads (DGED) while the script runs somewhere else
entirely, usually a bare system Python with no third-party packages at all.

This module has NO imports beyond os and sys, on purpose: it has to be
importable in exactly the broken interpreter where nothing else is, which
rules out putting it in dem2dged_lib.py (that module is one of the things
that fails to import).

Callers use it in their own ImportError handlers -- see audit_pure.py,
PACKAGE_v*.py, dem2dged_validate.py.
"""

import os
import sys

# Recommended command form, in one place so every message agrees.
CORRECT_FORM = "python %s"


def active_conda_prefix():
    """The activated conda environment's root, or None if none is active."""
    return os.environ.get("CONDA_PREFIX") or None


def active_conda_name():
    return os.environ.get("CONDA_DEFAULT_ENV") or None


def running_inside_active_env():
    """True if the interpreter executing this code lives inside the conda
    environment the shell has activated.

    False is the fingerprint of the file-association problem: a shell that
    has activated an environment, running an interpreter from somewhere
    else. None means no environment is active, so there is nothing to
    compare and this diagnostic does not apply.
    """
    prefix = active_conda_prefix()
    if not prefix:
        return None
    try:
        exe = os.path.realpath(sys.executable)
        root = os.path.realpath(prefix)
    except Exception:                                   # pragma: no cover
        return None
    return os.path.normcase(exe).startswith(os.path.normcase(root) + os.sep)


def interpreter_report(indent="       "):
    """A short, factual block naming what is actually running."""
    lines = [
        "interpreter: %s" % sys.executable,
        "version:     %s" % sys.version.split()[0],
        "conda env:   %s" % (active_conda_name() or "(none active)"),
        "CONDA_PREFIX:%s" % (" " + active_conda_prefix()
                             if active_conda_prefix() else " (not set)"),
    ]
    inside = running_inside_active_env()
    if inside is True:
        lines.append("This IS the interpreter from the activated environment.")
    elif inside is False:
        lines.append("This is NOT the interpreter from the activated "
                     "environment.")
    return "\n".join(indent + l for l in lines)


def missing_module_message(module, script=None, install_hint=None):
    """The full, actionable text for "module X is not importable here".

    ``script``: the script that failed, used to spell out the exact command
    that would have worked. Defaults to the running script's basename.
    ``install_hint``: the conda command to install the module, shown only
    when the interpreter IS the right one (i.e. when reinstalling is
    genuinely the fix, rather than the thing that wastes an hour).
    """
    script = script or os.path.basename(getattr(sys, "argv", ["script.py"])[0]
                                        or "script.py")
    inside = running_inside_active_env()

    out = ["ERROR: '%s' is not importable by the interpreter running this "
           "script." % module,
           "",
           interpreter_report(),
           ""]

    if inside is False:
        out += [
            "       THIS IS ALMOST CERTAINLY A COMMAND-FORM PROBLEM, NOT A "
            "MISSING PACKAGE.",
            "",
            "       Your shell has an environment activated, but this script "
            "is running",
            "       in a DIFFERENT Python. That happens when a .py file is "
            "launched by",
            "       name on Windows:",
            "",
            "           %s          <- uses the .py file association" % script,
            "           %s   <- uses the activated environment"
            % (CORRECT_FORM % script),
            "",
            "       `conda activate` changes PATH; it does not change the "
            "file",
            "       association. So the prompt still shows the environment "
            "name while",
            "       the script runs somewhere else. Re-run it with the second "
            "form.",
        ]
    else:
        out += [
            "       The interpreter above is the one you expect, so the "
            "package really",
            "       is missing from it:",
            "",
            "           %s" % (install_hint
                              or "conda install -c conda-forge %s" % module),
        ]
        if inside is None:
            out += [
                "",
                "       (No conda environment is active in this shell. From "
                "an Anaconda",
                "       Prompt, run `conda activate DGED` first -- and never "
                "install into",
                "       `base`.)",
            ]
    return "\n".join(out)


def require(module, script=None, install_hint=None):
    """Import ``module`` or exit with the diagnostic above.

    Returns the imported module so callers can write
    ``np = dem2dged_env.require("numpy")`` when they want the handle.
    """
    try:
        return __import__(module)
    except ImportError:
        sys.exit(missing_module_message(module, script=script,
                                        install_hint=install_hint))


if __name__ == "__main__":
    # `python dem2dged_env.py` prints the diagnosis for the current shell --
    # the fastest way to answer "why does the tool say my environment is
    # wrong when the prompt says otherwise?"
    print("dem2dged environment report")
    print("=" * 74)
    print(interpreter_report(indent="  "))
    print()
    for mod in ("numpy", "osgeo", "pytest", "PyInstaller"):
        try:
            __import__(mod)
            print("  %-12s OK" % mod)
        except ImportError as e:
            print("  %-12s MISSING (%s)" % (mod, e))
    inside = running_inside_active_env()
    if inside is False:
        print()
        print("  WARNING: this interpreter is not the activated "
              "environment's.")
        print("  If you launched this as 'dem2dged_env.py', re-run it as")
        print("  'python dem2dged_env.py' and compare the two outputs.")
