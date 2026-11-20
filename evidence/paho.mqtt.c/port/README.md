# paho.mqtt.c for QNX

[paho.mqtt.c](https://github.com/eclipse-paho/paho.mqtt.c) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `v1.3.16` + `patches/qnx.patch` |
| Result | **103/103 test programs pass on QNX; the tests' localhost services ran on the host (192.168.122.1)** |

**NOTE**: QNX ports are only supported from a Linux host operating system

## Create a workspace

```bash
mkdir -p ~/qnx_workspace && cd ~/qnx_workspace
git clone https://github.com/qnx-ports/build-files.git
git clone https://github.com/eclipse-paho/paho.mqtt.c paho.mqtt.c
git -C paho.mqtt.c checkout v1.3.16
git -C paho.mqtt.c apply $(pwd)/build-files/ports/paho.mqtt.c/patches/qnx.patch
```

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
cd ~/qnx_workspace
BUILD_TESTING=ON QNX_PROJECT_ROOT="$(pwd)/paho.mqtt.c" \
  make -C build-files/ports/paho.mqtt.c install JLEVEL=$(nproc)
```

This installs into the SDP, as the other ports do. To use a staging area instead, add `INSTALL_ROOT_nto=$HOME/qnx-staging USE_INSTALL_ROOT=true` to the `make` line.

The tests go to `<install root>/x86_64/usr/local/bin/paho.mqtt.c_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
TESTS=$QNX_TARGET/x86_64/usr/local/bin/paho.mqtt.c_tests   # or $HOME/qnx-staging/x86_64/...
ssh root@$IP "mkdir -p /data/paho.mqtt.c"
scp -r $TESTS/* root@$IP:/data/paho.mqtt.c/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/paho.mqtt.c/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/paho.mqtt.c/logs/`.

## What is QNX-specific


| File | Change | Why (QNX behavior) |
|---|---|---|
| `test/CMakeLists.txt` | do not link pthread on QNX | QNX has no libpthread: its functions are in libc ('cannot find -lpthread') |
| `src/SHA1.c` | include <net/netbyte.h> for be32toh on QNX | QNX declares be32toh in <net/netbyte.h> (declared when defined(__EXT_BSD)) |
| `src/WebSocket.c` | include <net/netbyte.h> for be32toh on QNX | QNX declares be32toh in <net/netbyte.h> (declared when defined(__EXT_BSD)) |
