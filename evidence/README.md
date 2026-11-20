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
- paho.mqtt.c (51/103): run against mosquitto, built from its official QNX port and running
  on the same QNX target. The 52 failures come from the test setup; none is traced to QNX yet:
  - 27 `ws` tests connect to `ws://localhost:1883`; this mosquitto has no WebSocket listener.
  - 16 connection-lost and offline-buffering tests (test1-6/7, test15-6/7, test9, test95)
    connect through paho's test proxy on port 1884, which was not running.
  - 9 MQTT 5 tests (test10, test11, test45) expect behaviour of paho's own test broker
    (paho.mqtt.testing), e.g. server topic aliases and UNSUBACK properties, that mosquitto
    doesn't have.
