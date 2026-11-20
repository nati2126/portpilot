# libcoap for QNX

[libcoap](https://github.com/obgm/libcoap) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `v4.3.5` |
| Result | **176/176 test cases pass on QNX (1/1 test programs pass on QNX)** |

**NOTE**: QNX ports are only supported from a Linux host operating system

## Create a workspace

```bash
mkdir -p ~/qnx_workspace && cd ~/qnx_workspace
git clone https://github.com/qnx-ports/build-files.git
git clone https://github.com/obgm/libcoap libcoap
git -C libcoap checkout v4.3.5
git clone https://github.com/jacklicn/CUnit cunit   # dependency: the official cunit port
```

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
cd ~/qnx_workspace
QNX_PROJECT_ROOT="$(pwd)/cunit" make -C build-files/ports/cunit install JLEVEL=$(nproc)
BUILD_TESTING=ON QNX_PROJECT_ROOT="$(pwd)/libcoap" \
  make -C build-files/ports/libcoap install JLEVEL=$(nproc)
```

This installs into the SDP, as the other ports do. To use a staging area instead, add `INSTALL_ROOT_nto=$HOME/qnx-staging USE_INSTALL_ROOT=true` to every `make` line.

The tests go to `<install root>/x86_64/usr/local/bin/libcoap_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
TESTS=$QNX_TARGET/x86_64/usr/local/bin/libcoap_tests   # or $HOME/qnx-staging/x86_64/...
ssh root@$IP "mkdir -p /data/libcoap"
scp -r $TESTS/* root@$IP:/data/libcoap/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/libcoap/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/libcoap/logs/`.

## What is QNX-specific

- **`-DCMAKE_REQUIRED_LIBRARIES=socket`** (in `common.mk`): sendmsg, recvmsg, socketpair, getpeereid... are in libsocket; without it CMake's checks fail and features are silently disabled
- **`-lsocket`** (in `common.mk`): freeaddrinfo and friends are in libsocket.so.4 on QNX, not in libc
