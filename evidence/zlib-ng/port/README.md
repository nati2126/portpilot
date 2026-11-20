# zlib-ng for QNX

[zlib-ng](https://github.com/zlib-ng/zlib-ng) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `2.3.3` |
| Result | **2/2 test programs pass on QNX** |

QNX ports are built from a Linux host.

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
git clone https://github.com/zlib-ng/zlib-ng zlib-ng
git -C zlib-ng checkout 2.3.3
STAGE=$HOME/qnx-staging     # install here instead of into the SDP

BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/zlib-ng \
  make -C build-files/ports/zlib-ng install -j8 INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1
```

Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the tests are in `bin/zlib-ng_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
ssh root@$IP "mkdir -p /data/zlib-ng"
scp -r $STAGE/x86_64/usr/local/bin/zlib-ng_tests/* root@$IP:/data/zlib-ng/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/zlib-ng/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/zlib-ng/logs/`.
