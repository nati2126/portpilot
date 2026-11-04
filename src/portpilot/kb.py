"""Knowledge base: Linux features that need attention on QNX, each with a cited source."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

FIX_KINDS = ("rule", "assisted", "manual", "none")
SEVERITIES = ("blocker", "fix", "warn", "info")


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    url: str


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    category: str
    linux: str
    qnx: str
    strategy: str
    fix: str
    severity: str
    sources: tuple[str, ...]
    headers: tuple[str, ...] = ()
    header_prefixes: tuple[str, ...] = ()
    header_map: dict[str, str] = field(default_factory=dict)
    functions: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    strings: tuple[str, ...] = ()
    link_libs: tuple[str, ...] = ()
    link: str = ""
    hints: dict[str, str] = field(default_factory=dict)
    requires_in_file: tuple[str, ...] = ()
    absent_in_file: tuple[str, ...] = ()
    quiet: bool = False
    trigger: str = "scan"

    @property
    def auto_fixable(self) -> str:
        return {"rule": "yes", "assisted": "assisted", "manual": "no", "none": "-"}[self.fix]


@dataclass(frozen=True)
class KnowledgeBase:
    rules: dict[str, Rule]
    sources: dict[str, Source]

    def rule(self, rule_id: str) -> Rule:
        return self.rules[rule_id]

    def scan_rules(self) -> list[Rule]:
        return [r for r in self.rules.values() if r.trigger == "scan"]

    def header_to_rule(self) -> dict[str, Rule]:
        out: dict[str, Rule] = {}
        for r in self.scan_rules():
            for h in (*r.headers, *r.header_map):
                out[h] = r
        return out

    def function_to_rule(self) -> dict[str, Rule]:
        return {f: r for r in self.scan_rules() for f in r.functions}

    def identifier_to_rule(self) -> dict[str, Rule]:
        return {i: r for r in self.scan_rules() for i in r.identifiers}

    def name_to_rule(self) -> dict[str, Rule]:
        """Every header, function and identifier of every rule (scan-, build- and test-time),
        for explaining a build error."""
        out: dict[str, Rule] = {}
        for r in self.rules.values():
            for n in (*r.headers, *r.header_map, *r.functions, *r.identifiers):
                out.setdefault(n, r)
        return out


def _tuple(d: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(d.get(key, ()))


def parse(text: str) -> KnowledgeBase:
    data = tomllib.loads(text)
    sources = {
        k: Source(key=k, title=v["title"], url=v["url"]) for k, v in data.get("sources", {}).items()
    }
    rules: dict[str, Rule] = {}
    for d in data.get("rule", []):
        rule = Rule(
            id=d["id"],
            title=d["title"],
            category=d["category"],
            linux=d["linux"],
            qnx=d["qnx"],
            strategy=d["strategy"],
            fix=d["fix"],
            severity=d["severity"],
            sources=_tuple(d, "sources"),
            headers=_tuple(d, "headers"),
            header_prefixes=_tuple(d, "header_prefixes"),
            header_map=dict(d.get("header_map", {})),
            functions=_tuple(d, "functions"),
            identifiers=_tuple(d, "identifiers"),
            strings=_tuple(d, "strings"),
            link_libs=_tuple(d, "link_libs"),
            link=d.get("link", ""),
            hints=dict(d.get("hints", {})),
            requires_in_file=_tuple(d, "requires_in_file"),
            absent_in_file=_tuple(d, "absent_in_file"),
            quiet=bool(d.get("quiet", False)),
            trigger=d.get("trigger", "scan"),
        )
        if rule.id in rules:
            raise ValueError(f"duplicate rule id {rule.id}")
        if rule.fix not in FIX_KINDS or rule.severity not in SEVERITIES:
            raise ValueError(f"rule {rule.id}: bad fix/severity {rule.fix}/{rule.severity}")
        missing = [s for s in rule.sources if s not in sources]
        if not rule.sources or missing:
            raise ValueError(f"rule {rule.id}: every rule needs known sources (missing {missing})")
        rules[rule.id] = rule
    return KnowledgeBase(rules=rules, sources=sources)


def load() -> KnowledgeBase:
    text = resources.files("portpilot").joinpath("data/kb.toml").read_text(encoding="utf-8")
    return parse(text)
