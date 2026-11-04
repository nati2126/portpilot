"""The command line, run in-process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from portpilot.cli import main
from portpilot.detect import detect


def test_detect(minilib: Path, tmp_path: Path) -> None:
    assert detect(minilib).primary == "cmake"
    (tmp_path / "configure.ac").write_text("AC_INIT\n")
    bs = detect(tmp_path)
    assert bs.primary == "autotools" and not bs.supported
    assert main(["detect", str(minilib)]) == 0


def test_scan_writes_matrix(minilib: Path, tmp_path: Path,
                            capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(["scan", str(minilib), "--no-sdp", "-o", str(out),
                 "-DCMAKE_REQUIRED_LIBRARIES=socket"]) == 0
    assert (out / "matrix.md").read_text(encoding="utf-8").startswith("# PortPilot scan")
    data = json.loads((out / "matrix.json").read_text(encoding="utf-8"))
    assert data["build_system"] == "cmake"
    assert "wrote" in capsys.readouterr().out


def test_scan_rejects_missing_dir(tmp_path: Path) -> None:
    assert main(["scan", str(tmp_path / "nope"), "--no-sdp"]) == 2
