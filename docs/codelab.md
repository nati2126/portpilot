# Port a C++ library to QNX 8.0 in 30 minutes with PortPilot

You will port [sockpp](https://github.com/fpagliughi/sockpp), a C++ socket library, to QNX
8.0, then run its own unit tests on a QNX 8.0 target in QEMU: **33 of 33 test cases pass**.
The result is a port in the official
[qnx-ports/build-files](https://github.com/qnx-ports/build-files) format, ready to contribute.

Along the way you will see four things that break real ports, and how each is found and
fixed:

- a test framework (Catch2) the SDP doesn't have
- socket functions that live in `libsocket` on QNX, not in libc
- tests that CMake tries to run on the build host
- a bug that **compiles cleanly** on QNX and only shows up when the tests run

**What you need:** a Linux host (or WSL 2 on Windows), a free
[QNX Everywhere](https://www.qnx.com/products/everywhere/) account with QNX SDP 8.0
installed, Python 3.11+, and about 2 GB of disk besides the SDP. No board: the target runs
in QEMU.

---

## 1. Install PortPilot (5 min)

```bash
git clone <portpilot-repo-url> portpilot
python3 -m venv ~/venvs/portpilot
~/venvs/portpilot/bin/pip install -e portpilot
export PATH=~/venvs/portpilot/bin:$PATH

source ~/qnx800/qnxsdp-env.sh             # your SDP install
portpilot sdp-index                        # once: what your SDP has (stays on your machine)

# the official ports, used when a library needs a dependency QNX has a port of
git clone https://github.com/qnx-ports/build-files ~/qnx-work/build-files
```

`sdp-index` records which headers, symbols and compiler macros **your** SDP provides.
Every later step checks its claims against it.

## 2. Make a QNX 8.0 target (10 min)

The SDP's `mkqnximage` builds a QNX 8.0 image for QEMU. It networks the VM through a
bridge, so install QEMU and libvirt's `virbr0` bridge first (Ubuntu shown):

```bash
sudo apt install qemu-system-x86 bridge-utils net-tools libvirt-daemon-system
sudo usermod -aG kvm,libvirt $USER        # then log out and in again
sudo chmod u+s /usr/lib/qemu/qemu-bridge-helper
echo "allow virbr0" | sudo tee /etc/qemu/bridge.conf

ssh-keygen -t ed25519 -N "" -f ~/.ssh/qnx_vm_ed25519
mkdir -p ~/qnx-work/vm-x86_64 && cd ~/qnx-work/vm-x86_64
mkqnximage --type=qemu --arch=x86_64 --ssh-ident=$HOME/.ssh/qnx_vm_ed25519.pub
```

You don't need to boot it yourself: PortPilot starts it when it needs it. To try it by hand,
run `mkqnximage --run=-h` (headless), `mkqnximage --getip`, and `ssh -i
~/.ssh/qnx_vm_ed25519 root@<ip> uname -a`. It prints `QNX ... 8.0.0 ... x86_64`.

## 3. See what needs porting (2 min)

```bash
git clone -b v1.0.0 https://github.com/fpagliughi/sockpp ~/src/sockpp
portpilot scan ~/src/sockpp -o ~/qnx-work/sockpp-scan
```

`matrix.md` is the dependency matrix that the
[QNX porting guide](https://www.qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.qpg/topic/porting_Dependency_mapping.html)
asks you to build by hand. For sockpp:

| Dependency | QNX equivalent | Strategy | Auto-fix |
|---|---|---|---|
| socket API lives in libsocket | `libsocket` (`-lsocket`) | link `-lsocket` | yes |
| sockaddr length field (`sin_len`) set only for BSD/macOS | `sockaddr_in` has `sin_len`, but QNX defines neither `BSD` nor `__APPLE__` | add `\|\| defined(__QNX__)` to the guard | yes |

It also lists what it ignored and why: `<linux/can.h>` is only used on a Linux-only path, and
`<winsock2.h>` only on Windows. Those are not work for you.

## 4. Port it: one command (3 min)

```bash
portpilot port https://github.com/fpagliughi/sockpp -o ~/qnx-work/sockpp \
  --vm ~/qnx-work/vm-x86_64 --known-hosts ~/qnx-work/known_hosts
```

PortPilot clones the latest release (`v1.0.0`, the way the official ports pin a tag), fixes
what it knows before building, then builds with `qcc` until the build passes. The real
output, shortened:

```text
[1/4] scan sockpp
      fix (bsd-sockaddr-len): set the sockaddr length field on QNX too  [src/inet_address.cpp:90]
      ... (3 more places)
[2/4] scaffold ~/qnx-work/sockpp/sockpp
[3/4] build attempt 1
      failed at configure: ... could not find a package configuration file provided by "Catch2"
      dependency Catch2: building the official QNX port
[3/4] build attempt 2
      failed at link: 19 errors, first: test_unix_dgram_socket.cpp undefined reference to 'socket'
      fix (link-socket): link -lsocket
[3/4] build attempt 3
      failed at configure: CatchAddTests.cmake:70 Error running test executable '.../unit_tests'
      fix (test-discovery-on-host): discover tests on the target, not on the build host
[3/4] build attempt 4
      built in 21s
[4/4] sockpp: BUILT in 80s, 4 build attempt(s), 1 tests for the target
      source patch: 2 files changed, 4 insertions(+), 4 deletions(-)
```

Each fix names a rule. Each rule in `src/portpilot/data/kb.toml` states the Linux behavior,
the QNX fact and its source:

- **Catch2:** the SDP doesn't ship it, but qnx-ports has an official port. PortPilot builds
  it from build-files into a staging folder next to the port, exactly as its README says,
  and points CMake at it.
- **`-lsocket`:** on QNX, `socket()`, `connect()` and friends are in `libsocket`.
- **Test discovery:** `catch_discover_tests()` runs the test program at build time to list
  its tests. A QNX binary can't run on a Linux host, so the port sets
  `CMAKE_CATCH_DISCOVER_TESTS_DISCOVERY_MODE=PRE_TEST` and the listing happens on the
  target.

## 5. Run the tests on QNX (2 min)

The same command goes on to test the port: it boots the VM, copies the test programs and the
shared libraries they need, and runs them with `qnxtests.sh`, a runner generated from
CTest that needs only `/bin/sh` on the target:

```text
[5/5] test sockpp on QNX target 192.168.122.202
      tests round 1: 1/1 pass
sockpp: 33/33 test cases pass on QNX
```

To re-run the tests later: `portpilot test ~/qnx-work/sockpp --vm ~/qnx-work/vm-x86_64`.

### Why the `sin_len` fix matters

Without it, sockpp still builds, but 3 test cases fail on QNX with:

```text
REQUIRE( sock.address() == ADDR )
with expansion:
  127.0.0.1:12345 == 127.0.0.1:12345
```

The two addresses print the same, yet compare unequal. sockpp compares addresses with
`memcmp`. QNX's network stack comes from BSD, so `struct sockaddr_in` has a `sin_len` byte
that `getsockname()` fills in. sockpp sets that byte only `#if defined(__APPLE__) ||
defined(BSD)`, and QNX defines neither, so its own addresses keep a 0 there. The patch adds
`|| defined(__QNX__)` in four places. No compiler warning points at this; you find it only by
running the tests on QNX.

## 6. Read the report (2 min)

Open `~/qnx-work/sockpp/report.html`. It is one self-contained page with the dependency
matrix, every change with its reason and source, each build attempt, the test results from
QNX, and the patch. Hand it to a reviewer as it is.

The port itself is in `~/qnx-work/sockpp/sockpp/`:

```text
Makefile  common.mk  nto-x86_64-o/  nto-aarch64-le/  qnx.nto.toolchain.cmake
patches/qnx.patch  qnxtests.sh  README.md
```

Each QNX setting in `common.mk` carries a comment with its reason. The port `README.md`
has build and test instructions and the result.

## 7. Contribute it (3 min)

```bash
portpilot pr ~/qnx-work/sockpp --author "Your Name <you@example.com>"
```

This writes what a port PR to build-files contains (compare the repo's own PRs, such as
#327 libwebsockets): `ports/sockpp/`, `.github/workflows/sockpp.yml` and a row in the port
table. They are committed on branch `add-sockpp` of a local clone, next to `PR.md`, which
holds the title, the QNX test results and a table of every change with its reason. It never
pushes. To open the PR, fork build-files, push the branch to your fork, and use `PR.md`.

## 8. When no rule covers an error

- **`--ai`:** errors no rule explains go to a local model through Ollama
  (`qwen2.5-coder:7b` by default). Its edit is kept only if the rebuild shows the error
  gone and nothing new broken; rejected edits are listed in the report. Your code never
  leaves your machine.
- **Redesigns:** some Linux APIs have no drop-in QNX equivalent, such as `epoll`
  (QNX: `ionotify`) and `inotify`. PortPilot does not fake those; the matrix marks them
  *manual*, with the porting guide's strategy.
- **Services:** some test suites need a server. paho.mqtt.c's tests need an MQTT broker, so
  `--service DIR='CMD'` runs one on the target during the tests, for example mosquitto built
  from its official QNX port.

## Recap

You went from a GitHub URL to a tested QNX 8.0 port in about 30 minutes:

1. `portpilot scan`: the porting guide's dependency matrix, checked against your SDP
2. `portpilot port`: fixes, build-files port, `qcc` build, dependencies from official ports
3. tests on a real QNX 8.0 target: 33/33
4. `portpilot pr`: a contribution in the shape build-files expects

Try it on the next library you need on QNX. `portpilot atlas` ranks what blocks 300
popular C/C++ libraries on QNX, if you're looking for one.
