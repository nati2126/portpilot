"""Classify test failures seen on the QNX target into knowledge-base rules.

Only signatures we have verified on QNX 8.0 are recognised; everything else is left to a human
(or the AI loop) with the failing test's log.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# gtest: 'Expected equality of these values:\n  a\n    Which is: "X"\n  b\n    Which is: "Y"'
_WHICH = re.compile(r'Which is: "([^"\n]*)"')
# unquoted numbers: 'Which is: 0.123456789' vs 'Which is: 0.12345678900000001' (yaml-cpp)
_WHICH_NUM = re.compile(r"Which is: ([-+]?\d+\.\d+(?:[eE][-+]?\d+)?)\s*$", re.M)
_HEXFLOAT = re.compile(r"^[-+]?0[xX][0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?[pP][-+]?\d+$")
_LONGDEC = re.compile(r"^[-+]?\d+\.?\d*$")
# a failed bitwise compare of a double after a parse (open62541: F-015)
_DOUBLE_BITS = re.compile(r"Assertion '([^'\n]*\bmemcmp\([^'\n]*sizeof\s*\(\s*(?:\w+_)?"
                          r"(?:double|Double|float|Float)\s*\)[^'\n]*)' failed")


@dataclass(frozen=True)
class FailureClass:
    rule_id: str
    evidence: str  # one line, quoted from the log


def _float_format_pair(a: str, b: str) -> bool:
    """Two renderings of the same float that differ the way QNX libc vs glibc do (F-002)."""
    if a == b:
        return False
    if _HEXFLOAT.match(a) and _HEXFLOAT.match(b):
        return True  # %a: C11 lets the leading hex digit differ
    if _LONGDEC.match(a) and _LONGDEC.match(b) and min(len(a), len(b)) >= 40:
        common = 0
        for x, y in zip(a, b, strict=False):
            if x != y:
                break
            common += 1
        return common >= 17  # same value to double precision, then the digits diverge
    return False


def _round_trip_pair(a: str, b: str) -> bool:
    """A double written with 17 significant digits and read back as a neighbouring value:
    QNX libc's printf gets the last digits wrong (F-002), so a write/parse round trip
    lands 1-2 ULP away."""
    fa, fb = float(a), float(b)
    if a == b or fa == fb or not (math.isfinite(fa) and math.isfinite(fb)):
        return False
    sig = max(len(re.split(r"[eE]", x.lstrip("+-"))[0].replace(".", "").lstrip("0"))
              for x in (a, b))
    return sig >= 17 and abs(fa - fb) <= 2 * math.ulp(max(abs(fa), abs(fb)))


def classify(log: str) -> list[FailureClass]:
    out: list[FailureClass] = []
    vals = _WHICH.findall(log)
    for a, b in zip(vals[::2], vals[1::2], strict=False):
        if _float_format_pair(a, b):
            short = (a if len(a) < 40 else a[:24] + "...")
            other = (b if len(b) < 40 else b[:24] + "...")
            out.append(FailureClass("float-format", f'"{short}" vs "{other}"'))
            break
    if not out:
        nums = _WHICH_NUM.findall(log)
        for a, b in zip(nums[::2], nums[1::2], strict=False):
            if _round_trip_pair(a, b):
                out.append(FailureClass("float-format", f"{a} vs {b} after a round trip"))
                break
    if not out and (m := _DOUBLE_BITS.search(log)):
        out.append(FailureClass("float-format", f"{m.group(1)[:80]} (double bits differ)"))
    return out
