# open62541 for QNX

[open62541](https://github.com/open62541/open62541) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `v1.5.10` + `patches/qnx.patch` |
| Result | **5028/5187 test cases pass on QNX (127/146 test programs pass on QNX) (failing: check_musl_inet_pton, check_types_builtin_json, check_json_config, check_pubsub_publish_json, check_pubsub_pds, check_pubsub_state_machine, check_pubsub_state_machine_extra, check_pubsub_connection_ud)** |

QNX ports are built from a Linux host.

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
git clone https://github.com/open62541/open62541 open62541
git -C open62541 checkout v1.5.10
git -C open62541 apply $(pwd)/build-files/ports/open62541/patches/qnx.patch
STAGE=$HOME/qnx-staging     # install here instead of into the SDP

BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/open62541 \
  make -C build-files/ports/open62541 install -j8 INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1
```

Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the tests are in `bin/open62541_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
ssh root@$IP "mkdir -p /data/open62541"
scp -r $STAGE/x86_64/usr/local/bin/open62541_tests/* root@$IP:/data/open62541/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/open62541/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/open62541/logs/`.

## What is QNX-specific

- **`-DCMAKE_POSITION_INDEPENDENT_CODE=ON`** (in `common.mk`): objects linked into a shared library must be PIC
- **`-lsocket`** (in `common.mk`): getsockopt and friends are in libsocket.so.4 on QNX, not in libc

| File | Change | Why (QNX behavior) |
|---|---|---|
| `arch/posix/eventloop_posix.h` | include <sys/queue.h> for LIST_ENTRY on QNX | QNX declares LIST_ENTRY in <sys/queue.h> |
| `arch/posix/eventloop_posix_interrupt.c` | include <sys/queue.h> for LIST_ENTRY on QNX | QNX declares LIST_ENTRY in <sys/queue.h> |
| `CMakeLists.txt` | do not link pthread on QNX | QNX has no libpthread: its functions are in libc ('cannot find -lpthread') |
| `CMakeLists.txt` | do not link -lpthread on QNX | QNX has no libpthread: its functions are in libc ('cannot find -lpthread') |
| `deps/nodesetLoader/CMakeLists.txt` | do not link pthread on QNX | QNX has no libpthread: its functions are in libc ('cannot find -lpthread') |
| `CMakeLists.txt` | do not link rt on QNX | QNX has no librt: its functions are in libc ('cannot find -lrt') |
| `CMakeLists.txt` | do not link -lrt on QNX | QNX has no librt: its functions are in libc ('cannot find -lrt') |
| `examples/CMakeLists.txt` | do not link rt on QNX | QNX has no librt: its functions are in libc ('cannot find -lrt') |
| `tests/CMakeLists.txt` | do not link subunit on QNX | the official QNX check port is built without subunit; Check runs tests without it |
| `tests/pubsub/check_pubsub_custom_state_machine.c` | include <netinet/in.h> for IPPROTO_UDP on QNX | QNX declares IPPROTO_UDP in <netinet/in.h> |
