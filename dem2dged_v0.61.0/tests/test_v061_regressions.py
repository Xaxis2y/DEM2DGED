# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.61.0
#
# Regression coverage for the v0.61.0 accuracy-reporting and source-gate
# improvements built on the v0.60.0 conversion safeguards.

import json

import numpy as np
import pytest

import dem2dged as cli
import dem2dged_compare as dc
import dem2dged_terrain as dt
from test_v060_regressions import _inspection


class _Logger:
    def __init__(self):
        self.messages = []

    def error(self, message):
        self.messages.append(message)


def test_primary_error_metrics_report_p90_and_maximum_tail_error():
    stats = dc._error_stats(np.array([-1.0, 2.0, 3.0, 100.0]))
    assert stats["rmse"] > stats["mae"]
    assert stats["p90_abs_err"] < stats["max_abs_err"]
    assert stats["max_abs_err"] == 100.0


def test_hold_preflight_stops_before_tile_production():
    logger = _Logger()
    with pytest.raises(SystemExit) as caught:
        cli._enforce_source_preflight(
            {"status": "HOLD", "issues": ["missing vertical reference"]},
            logger)
    assert caught.value.code == 2
    assert logger.messages == [
        "source metadata preflight HOLD: missing vertical reference"]


def test_explicit_metadata_override_is_serialized_as_non_pass(tmp_path):
    preflight = dt.source_preflight(
        _inspection(elevation_unit="foot", scale=0.3048),
        mode="hold",
        allow_unknown=True,
    )
    path = tmp_path / "source_preflight.json"
    dt.write_json(preflight, str(path))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "OVERRIDE"
    assert saved["allow_unknown"] is True
    assert saved["decision"] == "conversion may proceed"
    assert saved["status"] != "PASS"
