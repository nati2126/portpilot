# Ground truth: QNX 8.0 facts PortPilot relies on

We ported two libraries to QNX 8.0 by hand (fmt: 602/602 tests pass, nng: 64/64) and wrote
down every problem. Each rule in PortPilot's knowledge base that is not from the QNX docs
cites one of the sections below. Probes are in [`probes/`](../probes/).

Setup: QNX SDP 8.0, `qcc -Vgcc_ntox86_64` (gcc 12.2), QEMU x86_64 target, Nov 2026.

<a id="f-001"></a>
## F-001: regex is in libregex, not libc

- **Symptom:** `undefined reference to 'regcomp'` (also `regexec`, `regfree`).
- **Fact:** the POSIX regex functions are in `libregex.so.1`.
- **Fix:** link `-lregex`.
- **PortPilot:** the SDP index maps every symbol to its library, so any missing `-l` is found
  the same way (`-lsocket`, `-lregex`, `-lm`, ...).

<a id="f-002"></a>
## F-002: QNX printf differs on `%a` and very long `long double` output

- **Symptom:** 3 fmt tests compare against the platform `snprintf` and fail. fmt itself is
  right.
- **Fact:** QNX libc picks another leading hex digit for `%a` (allowed by C11) and is not exact
  for `%.1000Lf`.
- **Fix:** link the `muslflt` port (as other qnx-ports do); then 602/602 pass.
- **PortPilot:** warns when tests compare float output with the C library.

<a id="f-003"></a>
## F-003: there is no `<sys/errno.h>`

- **Symptom:** `fatal error: sys/errno.h: No such file or directory`.
- **Fix:** include `<errno.h>` (standard C, works everywhere).
- **PortPilot:** rule `nonstandard-sys-headers`, auto-fix.

<a id="f-004"></a>
## F-004: CMake checks fail silently on QNX

No build error: features are just switched off. In nng this disabled IPv6, `socketpair`,
`sendmsg`/`recvmsg` and peer credentials.

- **Cause A:** `sendmsg`, `recvmsg`, `socketpair`, `getpeereid` are in `libsocket`. A check
  links only libc, so it fails. **Fix:** `-DCMAKE_REQUIRED_LIBRARIES=socket`.
- **Cause B:** `AF_INET6` is defined only in `<sys/socket.h>`, and `<netinet/in.h>` does not
  include it. `check_symbol_exists(AF_INET6 netinet/in.h ...)` fails. **Fix:** check
  `"sys/socket.h;netinet/in.h"`.
- **PortPilot:** predicts every check result from the SDP. On nng it matches the real QNX
  `CMakeCache.txt` for 42 of 44 checks, 0 wrong (the other 2 are reported as unknown).

<a id="f-005"></a>
## F-005: pipes don't report POLLHUP when the writer closes

- **Symptom:** nng tests pass, then hang at exit.
- **Fact:** `poll()` on the read end returns `POLLIN` only. A socketpair returns `POLLIN|POLLHUP`.
  Probe: `pipe_pollhup.c`.
- **Fix:** don't use POLLHUP as a shutdown signal; use an explicit flag.
- **PortPilot:** rule `pollhup-pipe` (warning).

<a id="f-006"></a>
## F-006: `getaddrinfo` returns `EAI_ADDRFAMILY`

- **Fact:** for a malformed numeric host QNX returns `EAI_ADDRFAMILY` (1); glibc returns
  `EAI_NONAME`. Probe: `nng_errnos.c`.
- **Fix:** handle `EAI_ADDRFAMILY` (inside `#ifdef`) next to `EAI_NONAME`.
- **PortPilot:** rule `eai-addrfamily`.

<a id="f-007"></a>
## F-007: different errno for the same error

- **Fact:** UDP `sendmsg` to an `AF_UNIX` address fails with `ENOENT` (Linux: `EAFNOSUPPORT`).
  Probe: `nng_errnos.c`.
- **Fix:** check the address family before the call.

<a id="f-008"></a>
## F-008: connecting to a stale UNIX socket gives ENOENT

- **Fact:** `connect()` to a socket file with no listener fails with `ENOENT`, not
  `ECONNREFUSED`. Probe: `nng_errnos.c`.
- **Fix:** treat `ENOENT` like `ECONNREFUSED` when cleaning up stale sockets.
- **PortPilot:** rule `unix-stale-socket`.
- **Note:** errno *numbers* differ from Linux too (`ECONNREFUSED` is 261).

<a id="f-009"></a>
## F-009: `/dev/urandom` reads are slow

- **Fact:** one 4-byte read costs about 25 µs (a message to the `random` resource manager).
  Reading 4 KiB at once is about 180× cheaper per byte. Probe: `urandom_cost.c`.
- **Effect:** nng's 5 MiB test message, filled byte by byte, takes 137 s on QEMU.
- **PortPilot:** rule `urandom-cost` (info); test timeouts are scaled for QEMU.

<a id="f-010"></a>
## F-010: socketpair sockets have no peer credentials

- **Fact:** `getpeereid()` and `LOCAL_PEERCRED` fail with `ENOTCONN` on socketpair sockets.
  They work on `connect()`/`accept()` sockets. Probe: `peercred.c`.
- **PortPilot:** rule `so-peercred`.

<a id="f-011"></a>
## F-011: no libpthread, librt or libdl

- **Fact:** `-lpthread`, `-lrt` and `-ldl` fail with `cannot find -l...`. The functions are in
  libc. `-pthread` works. Probe: `link_flags.sh`.
- **Fix:** drop those libraries on QNX; use `Threads::Threads` and `${CMAKE_DL_LIBS}`.
- **PortPilot:** rules `link-libc-only` and `cmake-check-lib-in-libc`.

<a id="f-012"></a>
## F-012: Linux-only identifiers that stop the compile

Captured with qcc 12.2 (real output in `tests/data/diag/`).

- **`MSG_MORE`** is undeclared ("did you mean 'MSG_EOR'?"). It is a send-corking hint, so
  `#define MSG_MORE 0` under `#ifndef` keeps the behavior correct. The same applies to
  `O_NOATIME` and `MAP_POPULATE`. `MSG_NOSIGNAL` does exist on QNX.
- **`struct dirent` has no `d_type`**, and there is no `DT_DIR`. `fstatat()`, `dirfd()` and
  `AT_SYMLINK_NOFOLLOW` exist, so `fstatat(dirfd(d), e->d_name, &st, AT_SYMLINK_NOFOLLOW)` plus
  `S_ISDIR()` is a one-line replacement.
- **`strdupa` / `strndupa`** don't exist (only an implicit-declaration warning, then an
  undefined reference at link time). `<alloca.h>` exists. The shim works like glibc's
  macros (a gcc statement expression on `__builtin_alloca`), so the copy stays on the
  stack. `strdup()` instead would leak, which a 7B model proposed and the tests didn't catch.
- **`SO_PEERCRED`** is undeclared ("did you mean 'SO_PEERLABEL'?"). See F-010.
- **`<sys/syscall.h>`** does not exist. `gettid()` is declared in `<sys/process.h>`.
- **`cpu_set_t`** is unknown. Affinity uses QNX runmasks (`ThreadCtl(_NTO_TCTL_RUNMASK, ...)`),
  which is a redesign.
- **PortPilot:** `optional-flag` and `gnu-alloca-dup` (auto-fix), and `dirent-d-type`
  (AI-assisted, with this strategy given to the model).

<a id="sdp-inventory"></a>
## SDP inventory (from `portpilot sdp-index`)

PortPilot reads these facts from **your** SDP; it does not ship them.

- Present: `sys/inotify.h` (link `-lfsnotify`), `sys/auxv.h`, `poll`, `select`.
- Absent: `sys/epoll.h`, `sys/eventfd.h`, `sys/timerfd.h`, `sys/signalfd.h`, `endian.h`,
  `sys/endian.h`, `execinfo.h`, `getrandom`, `prctl`.
- `getentropy` and `arc4random` exist only inside `libunbound`, and `strchrnul` only inside
  `libasan`, so they don't count as available.
- `libatomic.a` is in `$QNX_TARGET/x86_64/lib/gcc/12.2.0/`.
