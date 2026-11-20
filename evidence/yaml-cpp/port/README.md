# yaml-cpp for QNX

[yaml-cpp](https://github.com/jbeder/yaml-cpp) built for QNX 8.0. Port generated and verified by PortPilot.

| | |
|---|---|
| Tested | QNX SDP 8.0, x86_64, QEMU target |
| Upstream | `yaml-cpp-0.9.0` |
| Result | **1008/1008 test cases pass on QNX (1/1 test programs pass on QNX)** |

QNX ports are built from a Linux host.

## Build

```bash
source ~/qnx800/qnxsdp-env.sh
git clone https://github.com/jbeder/yaml-cpp yaml-cpp
git -C yaml-cpp checkout yaml-cpp-0.9.0
STAGE=$HOME/qnx-staging     # install here instead of into the SDP

# Build the muslflt port into the same STAGE first (float formatting).
BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/yaml-cpp \
  make -C build-files/ports/yaml-cpp install -j8 INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1
```

Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the tests are in `bin/yaml-cpp_tests/`.

## Run the tests on the target

```bash
IP=<target-ip>        # QEMU: mkqnximage --getip
ssh root@$IP "mkdir -p /data/yaml-cpp"
scp -r $STAGE/x86_64/usr/local/bin/yaml-cpp_tests/* root@$IP:/data/yaml-cpp/
ssh root@$IP "TIMEOUT_SCALE=3 sh /data/yaml-cpp/qnxtests.sh"
```

Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are written to `/data/yaml-cpp/logs/`.

## What is QNX-specific

- **muslflt** (in `project_hooks.cmake`): tests expect glibc-style float output; QNX libc prints valid but different digits.
