"""Shared fixtures. Everything here is synthetic: CI has no QNX SDP, so the "SDP" is a small
hand-written index plus a few fake headers that mimic the QNX 8.0 layout facts PortPilot
relies on (socket APIs in libsocket, AF_INET6 only in <sys/socket.h>, no epoll, ...).
Nothing is copied from the real SDP."""

from __future__ import annotations

from pathlib import Path

import pytest

from portpilot import kb as kb_mod
from portpilot.kb import KnowledgeBase
from portpilot.models import ScanResult
from portpilot.scan import scan_project
from portpilot.sdp_index import SdpIndex

FIXTURES = Path(__file__).parent / "fixtures"

FAKE_HEADERS = {
    "sys/socket.h": "#define AF_UNIX 1\n#define AF_INET6 24\nint socket(int, int, int);\n"
                    "int recvmsg(int, void *, int);\nint connect(int, const void *, int);\n",
    "netinet/in.h": "#include <sys/types.h>\n#define IPPROTO_TCP 6\n",
    "sys/types.h": "typedef int pid_t;\n",
    "sys/un.h": "struct sockaddr_un { int sun_family; char sun_path[104]; };\n"
                "#define LOCAL_PEERCRED 1\n",
    "poll.h": "#define POLLHUP 0x10\nint poll(void *, unsigned, int);\n",
    "time.h": "#if defined(__EXT_ANSIC_201112)\n"
              "extern int timespec_get(void *__ts, int __base);\n#endif\n",
    "string.h": "unsigned long strlcpy(char *, const char *, unsigned long);\n"
                "void *memset(void *, int, unsigned long);\n",
    "unistd.h": "pid_t fork(void);\n",
    "netdb.h": "#define EAI_NONAME 8\n",
    "semaphore.h": "int sem_wait(void *);\n",
    "stdatomic.h": "#define atomic_flag_test_and_set(p) __atomic_test_and_set(p, 5)\n",
}


def make_sdp() -> SdpIndex:
    libc = "libc.so.6"
    sock = "libsocket.so.4"
    return SdpIndex(
        arch="x86_64",
        symbols={
            "socket": [sock], "recvmsg": [sock], "sendmsg": [sock], "connect": [sock],
            "poll": [libc], "sem_wait": [libc], "strlcpy": [libc], "timespec_get": [libc],
            "memset": [libc], "strncpy": [libc], "fork": [libc], "clock_gettime": [libc],
            "getentropy": ["libunbound.so.8"], "strchrnul": ["libasan.so.8"],
            "regcomp": ["libregex.so.1"], "regfree": ["libregex.so.1"], "__atomic_load_1": ["libatomic.a"],
        },
        headers=set(FAKE_HEADERS) | {"memory", "errno.h", "stdio.h", "stdlib.h"},
        libraries={"c", "socket", "regex", "atomic", "m", "unbound"},
        predefined_c={"__QNX__": "800", "__QNXNTO__": "1", "__unix__": "1", "__unix": "1",
                      "__x86_64__": "1", "__GNUC__": "12", "__STDC_VERSION__": "201710L",
                      "__ORDER_LITTLE_ENDIAN__": "1234", "__ORDER_BIG_ENDIAN__": "4321",
                      "__BYTE_ORDER__": "__ORDER_LITTLE_ENDIAN__"},
        predefined_cxx={"__QNX__": "800", "__cplusplus": "201703L", "__cpp_rtti": "199711L"},
        header_macros={"__EXT_ANSIC_201112"},
    )


@pytest.fixture
def kb() -> KnowledgeBase:
    return kb_mod.load()


@pytest.fixture
def fake_sdp() -> SdpIndex:
    return make_sdp()


@pytest.fixture
def qnx_target(tmp_path: Path) -> Path:
    inc = tmp_path / "qnx_target" / "usr" / "include"
    for rel, text in FAKE_HEADERS.items():
        p = inc / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path / "qnx_target"


@pytest.fixture
def minilib() -> Path:
    return FIXTURES / "minilib"


@pytest.fixture
def scan_minilib(minilib: Path, kb: KnowledgeBase, fake_sdp: SdpIndex, qnx_target: Path,
                 monkeypatch: pytest.MonkeyPatch) -> ScanResult:
    monkeypatch.setenv("QNX_TARGET", str(qnx_target))
    monkeypatch.delenv("QNX_HOST", raising=False)
    return scan_project(minilib, kb, fake_sdp)
