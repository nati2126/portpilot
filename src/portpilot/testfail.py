"""Classify test failures seen on the QNX target into knowledge-base rules.

Only signatures we have verified on QNX 8.0 are recognised; everything else is left to a human
(or the AI loop) with the failing test's log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# gtest: 'Expected equality of these values:\n  a\n    Which is: "X"\n  b\n    Which is: "Y"'
_WHICH = re.compile(r'Which is: "([^"\n]*)"')
_HEXFLOAT = re.compile(r"^[-+]?0[xX][0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?[pP][-+]?\d+$")
_LONGDEC = re.compile(r"^[-+]?\d+\.?\d*$")


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


def classify(log: str) -> list[FailureClass]:
    out: list[FailureClass] = []
    vals = _WHICH.findall(log)
    for a, b in zip(vals[::2], vals[1::2], strict=False):
        if _float_format_pair(a, b):
            short = (a if len(a) < 40 else a[:24] + "...")
            other = (b if len(b) < 40 else b[:24] + "...")
            out.append(FailureClass("float-format", f'"{short}" vs "{other}"'))
            break
    return out
