"""SdpIndex queries and persistence (synthetic index; the real one is never committed)."""

from __future__ import annotations

from portpilot.sdp_index import SdpIndex, _lib_name


def test_link_flags(fake_sdp: SdpIndex) -> None:
    assert fake_sdp.link_flag_for("poll") == ""
    assert fake_sdp.link_flag_for("socket") == "-lsocket"
    assert fake_sdp.link_flag_for("regcomp") == "-lregex"
    assert fake_sdp.link_flag_for("__atomic_load_1") == "-latomic"
    assert fake_sdp.link_flag_for("epoll_wait") is None


def test_non_providers_are_ignored(fake_sdp: SdpIndex) -> None:
    assert not fake_sdp.has_symbol("getentropy")  # only in libunbound (private copy)
    assert not fake_sdp.has_symbol("strchrnul")  # only in libasan (interceptor)


def test_json_roundtrip(fake_sdp: SdpIndex) -> None:
    back = SdpIndex.from_json(fake_sdp.to_json())
    assert back.symbols == fake_sdp.symbols
    assert back.headers == fake_sdp.headers
    assert back.predefined_c == fake_sdp.predefined_c
    assert back.header_macros == fake_sdp.header_macros


def test_lib_name() -> None:
    assert _lib_name("libsocket.so.4") == "socket"
    assert _lib_name("libregex.a") == "regex"
    assert _lib_name("libc++.so.2") == "c++"
    assert _lib_name("crt1.o") is None
