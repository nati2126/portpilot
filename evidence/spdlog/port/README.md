# spdlog for QNX

[spdlog](https://github.com/gabime/spdlog) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `v1.17.0` + `patches/qnx.patch` |
| Result | **180/180 test cases pass on QNX (1/1 test programs pass on QNX)** |

QNX ports are built from a Linux host.

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
git clone https://github.com/gabime/spdlog spdlog
git -C spdlog checkout v1.17.0
git -C spdlog apply $(pwd)/build-files/ports/spdlog/patches/qnx.patch
STAGE=$HOME/qnx-staging     # install here instead of into the SDP

BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/spdlog \
  make -C build-files/ports/spdlog install -j8 INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1
```

Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the tests are in `bin/spdlog_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
ssh root@$IP "mkdir -p /data/spdlog"
scp -r $STAGE/x86_64/usr/local/bin/spdlog_tests/* root@$IP:/data/spdlog/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/spdlog/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/spdlog/logs/`.

## What is QNX-specific

- **`-lsocket`** (in `common.mk`): sendto and friends are in libsocket.so.4 on QNX, not in libc
- **`-D_QNX_SOURCE`** (in `common.mk`): a strict -std= mode hides POSIX declarations in QNX headers

| File | Change | Why (QNX behavior) |
|---|---|---|
| `include/spdlog/details/os-inl.h` | include <sys/process.h> for getpid on QNX | QNX declares getpid in <sys/process.h> (declared when defined(__EXT_POSIX1_198808)) |
