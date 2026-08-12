#!/usr/bin/env python
"""
SPDX-License-Identifier: GPL-2.0-or-later
dem2dged Anaconda Environment Setup Script

This script creates and configures a dedicated Anaconda environment for dem2dged.
It handles environment creation, package installation, and validation.

Usage:
    python dem2dged_anaconda_environment.py [--remove] [--verify]

Options:
    --remove    Remove the existing environment
    --verify    Verify environment setup without creating it
    --help      Show this help message
"""

import subprocess
import sys
import argparse

ENVIRONMENT_NAME = "dem2dged_anaconda_environment"
PYTHON_VERSION = "3.11"

def run_command(cmd, description=""):
    """Execute a shell command and return success status."""
    if description:
        print(f"\n{description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=False, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def check_conda_available():
    """Check if conda is available in the system PATH."""
    result = subprocess.run("conda --version", shell=True, capture_output=True, text=True)
    return result.returncode == 0

def create_environment():
    """Create the Anaconda environment."""
    print("\n" + "="*80)
    print("dem2dged Anaconda Environment Setup")
    print("="*80)
    print(f"\nEnvironment Name: {ENVIRONMENT_NAME}")
    print(f"Python Version: {PYTHON_VERSION}")
    print()

    if not check_conda_available():
        print("ERROR: conda not found. Please ensure Anaconda is installed.")
        print("Make sure to run this script from Anaconda Prompt, not regular Command Prompt.")
        return False

    # Step 1: Create environment
    if not run_command(
        f"conda create -n {ENVIRONMENT_NAME} python={PYTHON_VERSION} -y",
        "Step 1: Creating environment"
    ):
        print("ERROR: Failed to create environment.")
        return False

    # Step 2: Install GDAL from conda-forge
    if not run_command(
        f'conda run -n {ENVIRONMENT_NAME} conda install -c conda-forge gdal -y',
        "Step 2: Installing GDAL from conda-forge"
    ):
        print("WARNING: GDAL installation may have had issues. Continuing...")

    # Step 3: Install core dependencies
    if not run_command(
        f'conda run -n {ENVIRONMENT_NAME} pip install --break-system-packages numpy matplotlib pillow scipy -y',
        "Step 3: Installing core dependencies"
    ):
        print("WARNING: Some dependencies may not have installed.")

    return True

def remove_environment():
    """Remove the Anaconda environment."""
    print(f"\nRemoving environment '{ENVIRONMENT_NAME}'...")
    if run_command(
        f"conda remove --name {ENVIRONMENT_NAME} --all -y",
        "Removing environment"
    ):
        print(f"Environment '{ENVIRONMENT_NAME}' successfully removed.")
        return True
    else:
        print(f"ERROR: Failed to remove environment '{ENVIRONMENT_NAME}'.")
        return False

def verify_environment():
    """Verify if the environment exists and has required packages."""
    print(f"\nVerifying environment '{ENVIRONMENT_NAME}'...")
    result = subprocess.run(
        f"conda list -n {ENVIRONMENT_NAME}",
        shell=True,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"[OK] Environment '{ENVIRONMENT_NAME}' exists.")
        print("\nInstalled packages:")
        print(result.stdout)
        return True
    else:
        print(f"[FAIL] Environment '{ENVIRONMENT_NAME}' not found.")
        return False

def print_usage():
    """Print usage instructions."""
    print("\n" + "="*80)
    print("Environment Setup Complete!")
    print("="*80)
    print(f"\nTo activate the environment, run from Anaconda Prompt:")
    print(f"  conda activate {ENVIRONMENT_NAME}")
    print(f"\nTo use dem2dged, navigate to the dem2dged directory and run:")
    print(f"  python dem2dged.py [input_raster] [output_folder] [options]")
    print(f"\nTo deactivate the environment:")
    print(f"  conda deactivate")
    print(f"\nTo remove the environment later (if needed):")
    print(f"  conda remove --name {ENVIRONMENT_NAME} --all")
    print()

def main():
    parser = argparse.ArgumentParser(
        description="Setup dem2dged Anaconda environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python dem2dged_anaconda_environment.py           # Create environment
  python dem2dged_anaconda_environment.py --verify  # Check if environment exists
  python dem2dged_anaconda_environment.py --remove  # Delete environment
        """
    )
    parser.add_argument("--remove", action="store_true", help="Remove the environment")
    parser.add_argument("--verify", action="store_true", help="Verify environment exists")

    args = parser.parse_args()

    if args.remove:
        success = remove_environment()
        sys.exit(0 if success else 1)
    elif args.verify:
        success = verify_environment()
        sys.exit(0 if success else 1)
    else:
        success = create_environment()
        if success:
            print_usage()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
