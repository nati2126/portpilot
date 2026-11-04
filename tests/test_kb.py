"""The knowledge base: every rule is well-formed and cites a source that exists."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from portpilot.kb import KnowledgeBase, parse

DOCS = Path(__file__).parent.parent / "docs"


def test_every_rule_cites_known_sources(kb: KnowledgeBase) -> None:
    assert len(kb.rules) >= 30
    for rule in kb.rules.values():
        assert rule.sources, rule.id
        for s in rule.sources:
            assert s in kb.sources, (rule.id, s)


def test_porting_guide_rows_are_covered(kb: KnowledgeBase) -> None:
    """The four rows of QNX's system-call replacement matrix."""
    for rid in ("fork", "epoll", "inotify", "timerfd"):
        assert "qnx-syscall" in kb.rule(rid).sources, rid


def test_ground_truth_anchors_exist(kb: KnowledgeBase) -> None:
    """Rules citing our own measurements point at a section of docs/ground-truth.md."""
    doc = (DOCS / "ground-truth.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r'<a id="([\w-]+)"></a>', doc))
    for sid, src in kb.sources.items():
        if src.url.startswith("docs/ground-truth.md#"):
            assert src.url.split("#", 1)[1] in anchors, sid


def test_parse_rejects_bad_rules() -> None:
    good_src = '[sources.s]\ntitle = "t"\nurl = "u"\n'
    with pytest.raises(ValueError):
        parse(good_src + '[[rule]]\nid = "x"\ntitle = "t"\ncategory = "c"\nlinux = "l"\n'
              'qnx = "q"\nstrategy = "s"\nfix = "maybe"\nseverity = "fix"\nsources = ["s"]\n')
    with pytest.raises(ValueError):
        parse(good_src + '[[rule]]\nid = "x"\ntitle = "t"\ncategory = "c"\nlinux = "l"\n'
              'qnx = "q"\nstrategy = "s"\nfix = "rule"\nseverity = "fix"\nsources = ["nope"]\n')
