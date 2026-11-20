"""AI edit handling (no model needed) and the QNX facts that go into the prompt."""

from __future__ import annotations

from pathlib import Path

from portpilot import ai
from portpilot import fixes as fx
from portpilot.diagnostics import parse
from portpilot.facts import qnx_facts, struct_members, where_declared
from portpilot.kb import KnowledgeBase
from portpilot.scaffold import PortSpec
from portpilot.sdp_index import SdpIndex

REPLY = """Here is the fix:
```c
FILE: src/proc.c
<<<<<<< SEARCH
    return (long)syscall(SYS_gettid);
=======
    return (long)gettid();
>>>>>>> REPLACE
```"""


def test_parse_reply_reads_fenced_blocks() -> None:
    p = ai.parse_reply(REPLY)
    assert p.error == "" and p.no_fix == ""
    assert [(e.path, e.search, e.replace) for e in p.edits] == [
        ("src/proc.c", "    return (long)syscall(SYS_gettid);", "    return (long)gettid();")]


def test_parse_reply_no_fix_and_garbage() -> None:
    assert ai.parse_reply("NO_FIX needs a redesign around ionotify").no_fix == \
        "needs a redesign around ionotify"
    assert ai.parse_reply("try adding a header").error == "no edit blocks in the reply"


def test_copied_line_numbers_are_dropped() -> None:
    assert ai._unnumber("12: int a;\n13:     b();") == "int a;\n    b();"
    assert ai._unnumber("x = 1;\n12: y") == "x = 1;\n12: y"  # not every line numbered: keep


def test_check_and_apply_and_revert(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    code = "#include <unistd.h>\nlong tid(void) {\n    return (long)syscall(SYS_gettid);\n}\n"
    (src / "proc.c").write_text(code)
    p = ai.parse_reply(REPLY)
    assert ai.check_edits(p, tmp_path, {"src/other.c"}).startswith("edit to src/proc.c is outside")
    assert ai.check_edits(p, tmp_path, {"src/proc.c"}) == ""
    orig = ai.apply_edits(p, tmp_path)
    assert "return (long)gettid();" in (src / "proc.c").read_text()
    # the SEARCH text is gone now: a second application must be refused
    assert "found 0 times" in ai.check_edits(p, tmp_path, {"src/proc.c"})
    ai.revert(tmp_path, orig)
    assert (src / "proc.c").read_text() == code


def test_large_edits_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a.c").write_text("int x;\n")
    big = "\n".join(f"int v{i};" for i in range(ai.MAX_CHANGED_LINES + 1))
    p = ai.Proposal(edits=[ai.Edit("a.c", "int x;", big)])
    assert "more than" in ai.check_edits(p, tmp_path, {"a.c"})


def test_prompt_has_the_error_line_and_no_line_numbers(tmp_path: Path) -> None:
    (tmp_path / "net.c").write_text("#include <sys/socket.h>\n"
                                    "int f(int s) {\n    return send(s, 0, 0, MSG_MORE);\n}\n")
    d = parse(f"{tmp_path}/net.c:3:30: error: 'MSG_MORE' undeclared "
              "(first use in this function)\n").errors[0]
    text = ai.build_prompt(d, "net.c", tmp_path, ["`MSG_MORE` is not declared"])
    assert "The error is on this line of net.c:\n    return send(s, 0, 0, MSG_MORE);" in text
    assert "- `MSG_MORE` is not declared" in text and "3: " not in text


def test_facts_from_headers_with_gates(qnx_target: Path) -> None:
    inc = qnx_target / "usr" / "include"
    hits = where_declared("timespec_get", inc)
    assert hits == ["`timespec_get` is declared in <time.h> (only when: "
                    "defined(__EXT_ANSIC_201112)): `extern int timespec_get(void *__ts, "
                    "int __base);`"]
    assert where_declared("MSG_MORE", inc) == []
    assert struct_members("struct sockaddr_un", inc) == \
        "<sys/un.h> struct sockaddr_un { int sun_family; char sun_path[104]; }"


def test_facts_for_a_diagnostic(kb: KnowledgeBase, qnx_target: Path) -> None:
    d = parse("net.c:3:30: error: 'MSG_MORE' undeclared (first use in this function)\n").errors[0]
    facts = qnx_facts(d, kb, None, qnx_target, code="syscall(SYS_fork);")
    assert any(f.startswith(kb.rule("optional-flag").title) for f in facts)
    assert "`MSG_MORE` is not declared in any QNX SDP header" in facts
    assert any(f.startswith("`fork` is declared in <unistd.h>") for f in facts)


def test_strdupa_gets_a_stack_shim_not_strdup(kb: KnowledgeBase, tmp_path: Path) -> None:
    (tmp_path / "str.c").write_text("#include <string.h>\n"
                                    "char *f(const char *p) {\n    char *c = strdupa(p);\n"
                                    "    return strdup(c);\n}\n")
    log = (f"{tmp_path}/str.c:3:15: warning: implicit declaration of function 'strdupa' "
           "[-Wimplicit-function-declaration]\n"
           "/usr/bin/ld: CMakeFiles/x.dir/str.c.o: in function `f':\n"
           "str.c:(.text+0x15): undefined reference to `strdupa'\n")
    parsed = parse(log)
    implicit = {w.symbol: w for w in parsed.warnings if w.kind == "implicit-decl"}
    assert set(implicit) == {"strdupa"}
    fixes, unfixed = fx.from_diagnostics(parsed.errors, kb, None, tmp_path, implicit)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["gnu-alloca-dup"]
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    text = (tmp_path / "str.c").read_text()
    assert "#define strdupa(s)" in text and "__builtin_alloca" in text
    assert "char *c = strdupa(p);" in text  # the call itself is unchanged
    # without the call site (no warning seen) the rule does not guess a file
    _, unfixed = fx.from_diagnostics(parsed.errors, kb, None, tmp_path)
    assert len(unfixed) == 1


def test_optional_flag_rule_defines_it_to_zero(kb: KnowledgeBase, tmp_path: Path) -> None:
    code = ("#include <sys/socket.h>\n#include <string.h>\n"
            "int f(int s) {\n    return send(s, 0, 0, MSG_MORE);\n}\n")
    (tmp_path / "net.c").write_text(code)
    diags = parse(f"{tmp_path}/net.c:4:30: error: 'MSG_MORE' undeclared "
                  "(first use in this function)\n").errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, None, tmp_path)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["optional-flag"]
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    assert (tmp_path / "net.c").read_text().startswith(
        "#include <sys/socket.h>\n#include <string.h>\n#ifndef MSG_MORE\n#define MSG_MORE 0")


def test_driver_kit_headers_are_not_offered_as_replacements(
        kb: KnowledgeBase, qnx_target: Path, fake_sdp: SdpIndex) -> None:
    """workflow's <sys/event.h> (kqueue): the model swapped in devs/sys/event.h (F-018)."""
    p = qnx_target / "usr" / "include" / "devs" / "sys" / "event.h"
    p.parent.mkdir(parents=True)
    p.write_text("struct kevent { int ident; };\n")
    d = parse("poller.c:26:11: fatal error: sys/event.h: No such file or directory\n").errors[0]
    facts = qnx_facts(d, kb, fake_sdp, qnx_target)
    assert any(f.startswith("kqueue: on QNX use poll()") for f in facts)
    header = next(f for f in facts if f.startswith("<sys/event.h> does not exist"))
    assert "Headers with that name" not in header
    assert "devs/sys/event.h belongs to the driver development kit" in header


def test_a_gated_declaration_gets_the_strict_mode_fix(kb: KnowledgeBase, qnx_target: Path) -> None:
    """workflow: 'strdup' was not declared (q++ -std=c++11; <string.h> gates it)."""
    d = parse("u.cc:3:5: error: 'timespec_get' was not declared in this scope\n").errors[0]
    facts = qnx_facts(d, kb, None, qnx_target)
    assert any(f.startswith("QNX declares `timespec_get` only when __EXT_ANSIC_201112 is set")
               and "#define _QNX_SOURCE" in f for f in facts)
