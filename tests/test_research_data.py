"""Transformación determinista sobre fixtures sintéticos, sin rendimientos."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab.experiments import ResearchGateError
from lab.research_data import apply_availability_policy


POLICY = {"asset": "AVAX", "available_from": "2020-09-22", "evidence_sha256": "a" * 64}


def panel():
    idx = pd.date_range("2020-07-12", "2020-09-24")
    raw = pd.DataFrame({"AVAX": np.nan, "BTC": np.arange(len(idx), dtype=float) + 100.}, index=idx)
    raw.loc[["2020-07-13", "2020-07-14"], "AVAX"] = [5.2, 4.8]
    raw.loc["2020-09-22":, "AVAX"] = [6.0, 5.9, 6.1]
    return raw


def test_quarantines_two_observations_with_dates_values_and_preserves_original():
    raw, policy = panel(), copy.deepcopy(POLICY)
    before = raw.copy(deep=True)
    derived, audit = apply_availability_policy(raw, policy)
    pd.testing.assert_frame_equal(raw, before)
    assert policy == POLICY and derived is not raw
    assert derived.loc[:"2020-09-21", "AVAX"].isna().all()
    assert audit["quarantined_count"] == 2
    assert [(row["date"], row["original_value"]) for row in audit["quarantine"]] == [
        ("2020-07-13", 5.2), ("2020-07-14", 4.8)]
    assert audit["missing_after"] == audit["missing_before"] + 2
    assert audit["rows_before_cutoff"] == len(raw.loc[:"2020-09-21"])
    assert audit["raw_mutated"] is audit["interpolation"] is audit["price_currency_conversion"] is False
    assert audit["bitso_listing_verified"] is audit["evidence_verified_by_helper"] is False
    json.dumps(audit, allow_nan=False)


def test_other_assets_and_post_cutoff_prices_are_exactly_preserved():
    raw = panel()
    derived, _ = apply_availability_policy(raw, POLICY)
    pd.testing.assert_series_equal(derived["BTC"], raw["BTC"])
    pd.testing.assert_frame_equal(derived.loc["2020-09-22":], raw.loc["2020-09-22":])
    assert derived.loc["2020-09-22", "AVAX"] == 6.0


@pytest.mark.parametrize("cutoff", ["2020-07-12", "2020-07-13", "2020-08-01", "2020-09-22"])
def test_prefix_causality_and_future_prices_do_not_change_past(cutoff):
    raw = panel()
    full, audit = apply_availability_policy(raw, POLICY)
    prefix, early = apply_availability_policy(raw.loc[:cutoff], POLICY)
    pd.testing.assert_frame_equal(full.loc[:cutoff], prefix)
    assert early["quarantine"] == [row for row in audit["quarantine"] if row["date"] <= cutoff]
    raw.loc[raw.index > pd.Timestamp(cutoff), "AVAX"] = 99999.
    altered, _ = apply_availability_policy(raw, POLICY)
    pd.testing.assert_frame_equal(altered.loc[:cutoff], prefix)


def test_idempotent_without_inventing_additional_quarantine_entries():
    first, _ = apply_availability_policy(panel(), POLICY)
    second, audit = apply_availability_policy(first, POLICY)
    pd.testing.assert_frame_equal(first, second)
    assert audit["quarantined_count"] == 0
    assert audit["missing_after"] == audit["missing_before"]


def test_internal_post_availability_gap_stays_missing_for_validation_to_reject():
    raw = panel()
    raw.loc["2020-09-23", "AVAX"] = np.nan
    derived, _ = apply_availability_policy(raw, POLICY)
    assert pd.isna(derived.loc["2020-09-23", "AVAX"])
    assert derived.loc["2020-09-24", "AVAX"] == raw.loc["2020-09-24", "AVAX"]


@pytest.mark.parametrize("policy", [
    {}, {"asset": "AVAX", "available_from": "2020-09-22"},
    {**POLICY, "asset": "BTC"}, {**POLICY, "available_from": "2020-09-23"},
    {**POLICY, "available_from": "2020-09-22T00:00:00Z"},
    {**POLICY, "evidence_sha256": ""}, {**POLICY, "evidence_sha256": "b" * 63},
    {**POLICY, "evidence_sha256": "G" * 64}, {**POLICY, "evidence_sha256": None},
    {**POLICY, "ffill": True},
])
def test_invalid_or_undeclared_policy_fails_closed(policy):
    with pytest.raises(ResearchGateError):
        apply_availability_policy(panel(), policy)


@pytest.mark.parametrize("malformation", ["duplicate", "unsorted", "intraday", "timezone", "missing_asset"])
def test_bad_index_or_missing_asset_is_rejected(malformation):
    raw = panel()
    if malformation == "duplicate":
        raw = pd.concat([raw.iloc[:1], raw])
    elif malformation == "unsorted":
        raw = raw.iloc[::-1]
    elif malformation == "intraday":
        raw.index += pd.Timedelta(hours=1)
    elif malformation == "timezone":
        raw.index = raw.index.tz_localize("UTC")
    else:
        raw = raw.drop(columns="AVAX")
    with pytest.raises(ResearchGateError):
        apply_availability_policy(raw, POLICY)


@pytest.mark.parametrize("value", [0., -1., np.inf, -np.inf])
def test_invalid_prices_are_not_laundered_by_quarantine(value):
    raw = panel()
    raw.loc["2020-07-13", "AVAX"] = value
    with pytest.raises(ResearchGateError, match="infinitos o no positivos"):
        apply_availability_policy(raw, POLICY)


def test_retained_primary_evidence_matches_pinned_bytes_and_daily_schema():
    directory = Path(__file__).resolve().parents[1] / "reports/data_quality"
    evidence_bytes = (directory / "avax_spot_availability.json").read_bytes()
    assert hashlib.sha256(evidence_bytes).hexdigest() == "b6483adcc33ea32a162e9cd4dad52224714832a8d3abf9aff5dc55ca93848850"
    evidence = json.loads(evidence_bytes)
    archive = evidence["daily_archive"]
    csv_bytes = (directory / archive["csv_file"]).read_bytes()
    assert hashlib.sha256(csv_bytes).hexdigest() == archive["csv_sha256"]
    assert archive["sha256"] == archive["checksum_text"].split()[0]
    assert hashlib.sha256(archive["checksum_text"].encode()).hexdigest() == archive["checksum_sha256"]
    rows = list(csv.reader(csv_bytes.decode().splitlines()))
    assert len(rows) == archive["rows"] == 9 and all(len(row) == 12 for row in rows)
    days = [str(pd.Timestamp(int(row[0]), unit="ms").date()) for row in rows]
    assert days == archive["dates"] == [str(day.date()) for day in pd.date_range("2020-09-22", "2020-09-30")]
    assert pd.Timestamp(int(rows[0][6]), unit="ms", tz="UTC").isoformat() == evidence["first_verified_daily_close_utc"]
    assert evidence["reference_market_type"] == "spot" and evidence["reference_quote_currency"] == "USDT"
    assert evidence["correction_contract"]["price_replacement"] is False
