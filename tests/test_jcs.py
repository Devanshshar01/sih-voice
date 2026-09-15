"""RFC 8785 (JSON Canonicalization Scheme) tests.

These anchor the two properties that matter for cross-language verification:
  1. Deterministic output for a given value (key order, whitespace).
  2. ECMAScript-compatible number formatting and string escaping.

The number-format cases below are the RFC 8785 §3.2.2.3 reference vectors.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.jcs import (  # noqa: E402
    CanonicalizationError,
    canonical_sha256_hex,
    canonicalize,
    canonicalize_bytes,
)


def test_object_keys_are_sorted():
    assert canonicalize({"b": 2, "a": 1, "c": 3}) == '{"a":1,"b":2,"c":3}'


def test_no_insignificant_whitespace():
    assert canonicalize({"a": [1, 2], "b": {"c": 3}}) == '{"a":[1,2],"b":{"c":3}}'


def test_nested_key_sorting_is_recursive():
    assert canonicalize({"z": {"y": 1, "x": 2}}) == '{"z":{"x":2,"y":1}}'


def test_deterministic_across_insertion_order():
    first = {"alpha": 1, "beta": [2, 3], "gamma": {"a": 1, "b": 2}}
    second = {"gamma": {"b": 2, "a": 1}, "beta": [2, 3], "alpha": 1}
    assert canonicalize(first) == canonicalize(second)


def test_unicode_is_not_escaped():
    # RFC 8785: only control chars, quote and backslash are escaped.
    assert canonicalize({"hi": "नमस्ते"}) == '{"hi":"नमस्ते"}'


def test_control_characters_use_short_or_u_escapes():
    assert canonicalize("a\nb\tc") == '"a\\nb\\tc"'
    assert canonicalize("\x00") == '"\\u0000"'
    assert canonicalize("\x1f") == '"\\u001f"'


def test_forward_slash_is_not_escaped():
    assert canonicalize("a/b") == '"a/b"'


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (-0.0, "0"),  # ECMAScript normalizes -0 to 0
        (1, "1"),
        (-1, "-1"),
        (1.5, "1.5"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (9007199254740992, "9007199254740992"),  # 2^53, exact in double
        (0.002, "0.002"),
        (1.0, "1"),
        (-1.5e-7, "-1.5e-7"),
    ],
)
def test_number_formatting(value, expected):
    assert canonicalize(value) == expected


def test_booleans_and_null():
    assert canonicalize({"t": True, "f": False, "n": None}) == '{"f":false,"n":null,"t":true}'


def test_nan_and_infinity_rejected():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(CanonicalizationError):
            canonicalize({"x": bad})


def test_canonicalize_bytes_is_utf8():
    assert canonicalize_bytes({"hi": "नमस्ते"}) == canonicalize({"hi": "नमस्ते"}).encode("utf-8")


def test_canonical_sha256_matches_manual_hash():
    import hashlib

    value = {"a": 1, "b": [2, 3]}
    expected = hashlib.sha256(canonicalize_bytes(value)).hexdigest()
    assert canonical_sha256_hex(value) == expected


def test_legacy_and_jcs_agree_on_simple_integer_payloads():
    """For the common evidence shape (ints/strings/lists) legacy == JCS.

    This documents *why* we can keep the legacy ledger path unchanged: for the
    integer/string-only payloads it produces, ``json.dumps(sort_keys=True)`` is
    byte-identical to JCS. The divergence is confined to floats and exotic keys.
    """
    import json

    payload = {"session_id": "sv-1", "max_risk_score": 75, "flags": ["a", "b"]}
    legacy = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert canonicalize(payload) == legacy
