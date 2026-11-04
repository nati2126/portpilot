"""Data model shared by the scanners and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Where in the project a finding is: library code matters most.
AREAS = ("lib", "test", "extra", "vendored")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    name: str  # the matched header / function / identifier / check / flag
    kind: str  # include | call | identifier | string | cmake-check | link | cmake-branch
    path: str  # relative to the project root, '/'-separated
    line: int
    area: str  # lib | test | extra | vendored
    guard: str  # none | feature | linux | other-os | qnx | build-feature | build-linux
    detail: str = ""  # human-readable specifics (e.g. "sendmsg is in libsocket.so.4")

    @property
    def guarded(self) -> bool:
        return self.guard != "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    root: str
    build_system: str
    build_markers: dict[str, list[str]]
    files_scanned: int
    sdp_index_used: bool
    findings: list[Finding] = field(default_factory=list)
    qnx_aware: list[str] = field(default_factory=list)  # places already mentioning QNX
    elapsed_s: float = 0.0
    # predicted configure-check results on QNX (configure.Prediction.to_dict())
    configure: list[dict[str, Any]] = field(default_factory=list)
