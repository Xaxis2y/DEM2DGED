#!/usr/bin/env bash
# ============================================================
#  dem2dged  –  Linux / macOS install script (conda)
#  SPDX-License-Identifier: GPL-2.0-or-later
#  Copyright (c) 2026 Eui Soo SON
# ============================================================
set -e

echo ""
echo "  dem2dged installer"
echo "  =================="
echo ""

echo "[1/2] Creating conda environment 'DGED' with GDAL …"
conda create --name DGED --channel conda-forge gdal python=3.10 -y

echo ""
echo "[2/2] Done!  Activate and run with:"
echo ""
echo "  conda activate DGED"
echo "  cd $(dirname "$0")"
echo "  python dem2dged.py my_dem.tif output_folder"
echo ""
echo "  (add --help for all options)"
echo ""
