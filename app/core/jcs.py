"""RFC 8785 — JSON Canonicalization Scheme (JCS).

WHY A DEDICATED MODULE?
  The legacy evidence ledger (``app/services/evidence_anchor.py``) hashes with
  ``json.dumps(..., sort_keys=True, separators=(",", ":"))``. That is *nearly*
  canonical, but it is not RFC 8785: Python's float formatting differs from
  ECMAScript's ``Number::toString`` (e.g. ``1e+20`` vs ``100000000000000000000``),
  and Python sorts object keys by Unicode code point rather than by UTF-16 code
  unit. Both differences are observable and would make two honest
  implementations of the same data disagree on the hash.

  RFC 8785 removes that ambiguity, so an independent verifier (in any language)
  can recompute the exact bytes we hashed. That property is what makes a Merkle
  root + on-chain commitment meaningful.

WHAT THIS IMPLEMENTS
  1. Object keys sorted by UTF-16 code unit (not code point).
  2. Strings escaped with ECMAScript ``JSON.stringify`` semantics: only control
     characters, ``"`` and ``\\`` are escaped; everything else (including all
     non-ASCII and ``/``) is emitted verbatim as UTF-8.
  3. Numbers serialized with ECMAScript ``Number::toString`` (the shortest
     round-tripping decimal form, with ES6 fixed/exponential switch points).
  4. No insignificant whitespace. ``NaN``/``Infinity`` are rejected.

REFERENCES
  - RFC 8785: https://www.rfc-editor.org/rfc/rfc8785
  - ECMAScript Number::toString: https://tc39.es/ecma262/#sec-number.prototype.tostring

SCOPE NOTE
  The legacy ledger path is intentionally left unchanged so existing, already
  anchored evidence hashes stay verifiable. Only the new Merkle evidence layer
  uses JCS. See ``docs/blockchain-evidence.md``.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

__all__ = [
    "CanonicalizationError",
    "canonicalize",
    "canonicalize_bytes",
    "canonical_sha256_hex",
]

# The ECMAScript-safe integer range. Integers inside it are serialized exactly
# as their decimal digits (identical to their IEEE-754 double representation).
_SAFE_INT_MAX = 2**53

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


class CanonicalizationError(ValueError):
    """Raised when a value cannot be serialized under RFC 8785.

    Examples: NaN/Infinity, non-string object keys, or unsupported Python types.
    """


def _escape_string(value: str) -> str:
    """Return *value* as an ECMAScript-compatible JSON string literal."""
    out: list[str] = ['"']
    for ch in value:
        escaped = _ESCAPES.get(ch)
        if escaped is not None:
            out.append(escaped)
        elif ch < " ":
            # All other C0 control characters use the \u00XX form.
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number_to_string(value: int | float) -> str:
    """Serialize a number exactly as ECMAScript ``Number::toString``.

    ``bool`` is handled by the caller (it is a JSON literal, not a number) but is
    rejected here as a defensive guard, since ``isinstance(True, int)`` is True.
    """
    if isinstance(value, bool):  # defensive: callers should handle bool first
        raise CanonicalizationError("Booleans must be serialized as JSON literals.")

    if isinstance(value, int):
        if abs(value) <= _SAFE_INT_MAX:
            return str(value)
        value = float(value)  # outside safe range, fall through to ES6 formatting

    if not isinstance(value, float):
        raise CanonicalizationError(f"Unsupported numeric type: {type(value)!r}")

    if math.isnan(value) or math.isinf(value):
        raise CanonicalizationError("NaN and Infinity are not valid JSON numbers.")

    if value == 0.0:
        return "0"  # normalizes -0.0 to "0", matching ECMAScript

    sign = "-" if value < 0 else ""

    # ``repr`` gives the shortest round-tripping decimal for a float. Parse it
    # back through Decimal to obtain exact (digits, exponent) so we can reformat
    # using the ECMAScript rules rather than Python's repr rules.
    dec = Decimal(repr(abs(value)))
    sign_digits, digit_tuple, exponent = dec.as_tuple()
    digits = "".join(str(d) for d in digit_tuple)

    # Strip trailing zeros (they do not change the value; they only shift the
    # exponent, and n = exponent + k is invariant under this operation).
    stripped = digits.rstrip("0") or "0"
    exponent += len(digits) - len(stripped)

    k = len(stripped)          # number of significant digits
    n = exponent + k           # position of the decimal point

    if k <= n <= 21:
        # Integer with trailing zeros (e.g. 1e20 -> "100000000000000000000").
        return sign + stripped + "0" * (n - k)
    if 0 < n <= 21:
        # Simple decimal point (e.g. 1.5 -> "1.5").
        return sign + stripped[:n] + "." + stripped[n:]
    if -6 < n <= 0:
        # Leading zero decimal (e.g. 1e-6 -> "0.000001").
        return sign + "0." + "0" * (-n) + stripped

    # Exponential notation (ECMAScript switches here for very large/small).
    e = n - 1
    e_sign = "+" if e >= 0 else "-"
    if k == 1:
        return f"{sign}{stripped}e{e_sign}{abs(e)}"
    return f"{sign}{stripped[0]}.{stripped[1:]}e{e_sign}{abs(e)}"


def _write(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
        return
    if isinstance(value, bool):
        out.append("true" if value else "false")
        return
    if isinstance(value, str):
        out.append(_escape_string(value))
        return
    if isinstance(value, (int, float)):
        out.append(_number_to_string(value))
        return
    if isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write(item, out)
        out.append("]")
        return
    if isinstance(value, dict):
        out.append("{")
        # RFC 8785: sort keys by UTF-16 code unit. Encoding to UTF-16-BE and
        # comparing the byte strings reproduces UTF-16 code-unit ordering exactly
        # (this differs from code-point order for supplementary-plane keys).
        for index, key in enumerate(sorted(value.keys(), key=lambda s: s.encode("utf-16-be"))):
            if not isinstance(key, str):
                raise CanonicalizationError("JSON object keys must be strings.")
            if index:
                out.append(",")
            out.append(_escape_string(key))
            out.append(":")
            _write(value[key], out)
        out.append("}")
        return
    raise CanonicalizationError(f"Unsupported type for canonicalization: {type(value)!r}")


def canonicalize(value: Any) -> str:
    """Return the RFC 8785 canonical JSON string for *value*."""
    out: list[str] = []
    _write(value, out)
    return "".join(out)


def canonicalize_bytes(value: Any) -> bytes:
    """Return the canonical JSON string encoded as UTF-8 (the exact hashed bytes)."""
    return canonicalize(value).encode("utf-8")


def canonical_sha256_hex(value: Any) -> str:
    """Return ``sha256(canonicalize_bytes(value))`` as a lowercase hex digest."""
    import hashlib

    return hashlib.sha256(canonicalize_bytes(value)).hexdigest()
