"""Unit tests for the shared util helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lth_util import parse_iso_datetime


def test_parse_iso_datetime_with_z_suffix():
    result = parse_iso_datetime("2024-01-15T10:30:00.000Z")
    assert result == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_parse_iso_datetime_with_offset():
    result = parse_iso_datetime("2024-01-15T10:30:00+00:00")
    assert result == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_parse_iso_datetime_naive_assumes_utc():
    result = parse_iso_datetime("2024-01-15T10:30:00")
    assert result == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_parse_iso_datetime_preserves_non_utc_offset():
    result = parse_iso_datetime("2024-01-15T10:30:00+10:00")
    assert result is not None
    assert result.utcoffset().total_seconds() == 36000


@pytest.mark.parametrize("value", [None, "", "not-a-date", 42, ["2024-01-15"]])
def test_parse_iso_datetime_returns_none_on_invalid(value):
    assert parse_iso_datetime(value) is None
