"""scan_cmake.py: the CMake command parser and project wrapper functions."""

from __future__ import annotations

from portpilot.scan_cmake import _find_wrappers, _split_args, parse_commands


def test_split_args_keeps_empty_quoted_argument() -> None:
    assert _split_args('${LIB} ${SYM} "" ${DEF}') == ["${LIB}", "${SYM}", "", "${DEF}"]
    assert _split_args('"struct ${STR}" ${MEM}') == ["struct ${STR}", "${MEM}"]


def test_parse_commands_conditions() -> None:
    text = """
    if (A) # comment with if(B)
      set(X 1)
    elseif (B)
      set(Y 1)
    else ()
      set(Z 1)
    endif ()
    """
    cmds = {c.args[0]: c for c in parse_commands(text) if c.name == "set"}
    assert cmds["X"].conds == (("A", True),)
    assert cmds["Y"].conds == (("A", False), ("B", True))
    assert cmds["Z"].conds == (("A", False), ("B", False))
    ifs = [c for c in parse_commands(text) if c.name in ("if", "elseif", "else", "endif")]
    assert len({c.chain for c in ifs}) == 1
    assert cmds["X"].line == 3


def test_function_bodies_and_wrappers() -> None:
    text = """
    function(my_check_sym SYM HDRS DEF)
        check_symbol_exists(${SYM} "${HDRS}" ${DEF})
    endfunction()
    function(my_check_struct STR MEM HDR DEF)
        check_struct_has_member("struct ${STR}" ${MEM} ${HDR} ${DEF})
    endfunction()
    function(my_defines)
        target_compile_definitions(lib PRIVATE ${ARGN})
    endfunction()
    my_check_sym(AF_INET6 netinet/in.h HAVE_INET6)
    """
    cmds = parse_commands(text)
    body = [c for c in cmds if c.name == "check_symbol_exists"]
    assert body and body[0].in_body
    assert not [c for c in cmds if c.name == "my_check_sym"][0].in_body
    w = _find_wrappers([cmds])
    assert w["my_check_sym"].kind == "check"
    assert w["my_check_sym"].resolve(["AF_INET6", "netinet/in.h", "HAVE_INET6"]) == [
        "AF_INET6", "netinet/in.h", "HAVE_INET6"]
    assert w["my_check_struct"].resolve(["msghdr", "msg_control", "sys/socket.h", "H"])[0] == \
        "struct msghdr"
    assert w["my_defines"].kind == "define"
