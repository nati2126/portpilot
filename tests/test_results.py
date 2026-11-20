"""portpilot results: the table comes only from run.json."""

from __future__ import annotations

import json
from pathlib import Path

from portpilot.results import collect, patch_lines, to_markdown


def test_patch_lines() -> None:
    assert patch_lines("7 files changed, 17 insertions(+), 8 deletions(-)") == 25
    assert patch_lines("1 file changed, 1 insertion(+)") == 1
    assert patch_lines("") == 0


def _write(d: Path, **run: object) -> None:
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps(run))


def test_table_from_runs(tmp_path: Path) -> None:
    _write(tmp_path / "b" / "yaml-cpp", name="yaml-cpp", commit="yaml-cpp-0.9.0", ok=True,
           elapsed_s=300, patch_stat="", pre_fixes=[],
           attempts=[], test_rounds=[{"fixes": [{"rule": "float-format"}]}],
           target_tests={"passed": 1, "total": 1, "cases": [1008, 1008]})
    _write(tmp_path / "b" / "nng", name="nng", commit="v1.9.0", ok=False, elapsed_s=60,
           patch_stat="1 file changed, 3 insertions(+)",
           pre_fixes=[{"rule": "link-socket"}], attempts=[{"applied": [{"rule": "ai-edit"}]}],
           ai=[{"result": "accepted"}, {"result": "rejected"}, {"result": "no_fix"}])
    rows = collect([tmp_path / "b"])
    assert [r["library"] for r in rows] == ["nng", "yaml-cpp"]
    md = to_markdown(rows)
    assert md.startswith("1/2 libraries built for QNX 8.0 from their upstream release; 1 tested")
    assert "| nng | `v1.9.0` | no | 1 | 2 (1) | 3 | not run | 1.0 min |" in md
    assert "| yaml-cpp | `yaml-cpp-0.9.0` | yes | 0 | 1 (0) | 0 | 1008/1008 cases (1/1 programs)" \
        in md
    assert collect([tmp_path / "b" / "nng"])[0]["library"] == "nng"  # a run dir itself
    assert "Local AI: 3 proposals, 1 accepted (verified by rebuild or retest), 2 rejected" in md


def test_no_tests_built(tmp_path: Path) -> None:
    _write(tmp_path / "efsw", name="efsw", commit="1.7.3", ok=True, elapsed_s=24,
           target_tests={"passed": 0, "total": 0})
    md = to_markdown(collect([tmp_path]))
    assert md.startswith("1/1 libraries built for QNX 8.0 from their upstream release; 0 tested")
    assert "| no tests built |" in md


def test_text_table(tmp_path: Path) -> None:
    from portpilot.results import to_text
    _write(tmp_path / "sockpp", name="sockpp", commit="v1.0.0", ok=True, elapsed_s=78,
           patch_stat="2 files changed, 4 insertions(+), 4 deletions(-)",
           target_tests={"passed": 1, "total": 1, "cases": [33, 33]})
    txt = to_text(collect([tmp_path]))
    lines = txt.splitlines()
    assert lines[0].startswith("1/1 libraries built")
    assert lines[2].split() == ["Library", "Release", "Built", "Attempts", "Fixes", "Patch",
                                "Tests", "on", "QNX", "Time"]
    assert lines[4].split()[:6] == ["sockpp", "v1.0.0", "yes", "0", "0", "8"]
    assert "33/33 cases (1/1 programs)" in lines[4] and "|" not in txt
