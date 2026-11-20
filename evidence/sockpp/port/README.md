# sockpp for QNX

[sockpp](https://github.com/fpagliughi/sockpp) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `v1.0.0` + `patches/qnx.patch` |
| Result | **33/33 test cases pass on QNX (1/1 test programs pass on QNX)** |

QNX ports are built from a Linux host.

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
git clone https://github.com/fpagliughi/sockpp sockpp
git -C sockpp checkout v1.0.0
git -C sockpp apply $(pwd)/build-files/ports/sockpp/patches/qnx.patch
STAGE=$HOME/qnx-staging     # install here instead of into the SDP

BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/sockpp \
  make -C build-files/ports/sockpp install -j8 INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1
```

Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the tests are in `bin/sockpp_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
ssh root@$IP "mkdir -p /data/sockpp"
scp -r $STAGE/x86_64/usr/local/bin/sockpp_tests/* root@$IP:/data/sockpp/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/sockpp/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/sockpp/logs/`.

## What is QNX-specific

- **`-DCMAKE_CATCH_DISCOVER_TESTS_DISCOVERY_MODE=PRE_TEST`** (in `common.mk`): test programs only run on the QNX target
- **`-lsocket`** (in `common.mk`): socket and friends are in libsocket.so.4 on QNX, not in libc

| File | Change | Why (QNX behavior) |
|---|---|---|
| `src/inet6_address.cpp` | set the sockaddr length field on QNX too | QNX's sockaddr has sin_len/sa_len like BSD, but QNX defines neither BSD nor __APPLE__ |
| `src/inet_address.cpp` | set the sockaddr length field on QNX too | QNX's sockaddr has sin_len/sa_len like BSD, but QNX defines neither BSD nor __APPLE__ |
