# Evidence: real runs on QNX 8.0

Outputs of `portpilot port <github url>` runs, unedited apart from replacing the host home
directory with `~`. `collect.sh` copied them; rerun it to refresh.

- `results.md`: the summary table (`portpilot results`).
- `qnx-target.txt`: `uname -a` and `pidin info` from the QEMU target (QNX 8.0.0, x86_64).
- `<library>/port/`: the generated port in the qnx-ports/build-files layout (`common.mk`,
  `nto-x86_64-o/Makefile`, `qnx.nto.toolchain.cmake`, `patches/qnx.patch`, `qnxtests.sh`).
- `<library>/report.html`: the run report: dependency matrix, every change and why, build
  attempts, QNX test results.
- `<library>/qnx/qnxtests.out`: one `QNXTEST <test> PASS|FAIL rc=.. secs=..` line per
  test, as printed on the QNX target. `qnx/logs/` has each test's output (open62541: only
  the failing tests, since the suite is large).

No QNX SDP files and no binaries: `collect.sh` refuses to copy a binary file.

Known failures, and why:

- open62541 (19 of 146 programs, all logs in `open62541/qnx/logs/`), not yet fixed:
  - PubSub over UDP multicast (most of the 19): `Invalid connection parameters to
    "224.0.0.22"`. open62541 chooses the multicast interface only in `__linux__` and
    `__APPLE__` branches. `check_pubsub_udp_unicast`: the received value differs from the
    published one.
  - `check_types_builtin_json`: a double is not bit-identical after a JSON round trip (QNX
    float formatting, as in yaml-cpp before the `float-format` fix).
  - `check_musl_inet_pton`: errno is 3 (`ESRCH`), not `EAFNOSUPPORT`. The function sets
    `EAFNOSUPPORT`, but the test reads errno after another passing `ck_assert`, which calls
    into libcheck; probably that call changes errno on QNX (not verified).
  - `check_json_config` reads a file from the source tree, which is not on the target;
    `check_client_subscriptions` sees a connection closed with error 261.
- paho.mqtt.c (103/103): the client runs on QNX; paho's own test broker (paho.mqtt.testing)
  and test proxy (`test/mqttsas.py`) run on the host, as in paho's CI
  (`portpilot test --localhost 192.168.122.1`). Earlier runs:
  - 95/103: the 8 `serverURIs` tests first try the host name `rubbish`, and the VM network's
    DNS forwarded plain names to the WSL/Windows resolver, which took 30 s to say "not
    found", as long as the tests wait. Fixed in the test network (libvirt
    `<dns forwardPlainNames='no'/>`), not in paho.
  - 51/103 against mosquitto on the QNX target: no WebSocket listener, no proxy, and no
    MQTT 5 behaviour of paho's broker (server topic aliases, UNSUBACK properties).
