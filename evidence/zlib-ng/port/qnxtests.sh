#!/bin/sh
# QNX test runner for zlib-ng: 2 tests, generated from CTest by PortPilot.
# Run from anywhere: sh qnxtests.sh   (set TIMEOUT_SCALE=3 on QEMU)
here=$(cd "$(dirname "$0")" && pwd); cd "$here" || exit 1
export LD_LIBRARY_PATH="$here${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
S=${TIMEOUT_SCALE:-1}; mkdir -p logs; pass=0; fail=0; tmo=0

run() {  # run <name> <timeout> <cmd...>
  n=$1; to=$(( $2 * S )); shift 2; s=$(date +%s)
  "$@" > "logs/$n.out" 2>&1 </dev/null & p=$!
  # watchdog: polls each second, so no stray sleep outlives the test (a leftover
  # 'sleep $to' kept the ssh session open for the full timeout)
  ( i=0; while [ $i -lt $to ]; do sleep 1; kill -0 $p 2>/dev/null || exit 0;
    i=$((i+1)); done; kill -9 $p ) >/dev/null 2>&1 </dev/null & w=$!
  wait $p; rc=$?; kill $w 2>/dev/null; e=$(( $(date +%s) - s ))
  if [ $rc -eq 137 ] && [ $e -ge $to ]; then tmo=$((tmo+1)); fail=$((fail+1))
    echo "QNXTEST $n TIMEOUT rc=$rc secs=$e limit=$to"
    if [ $pass -eq 0 ] && [ $tmo -ge ${ABORT_AFTER_TIMEOUTS:-3} ]; then  # all hang: stop
      echo "QNXTEST-ABORT the first $tmo tests timed out: the programs probably hang"
      echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"
      exit 2; fi; return; fi
  [ -n "$INVERT" ] && { [ $rc -eq 0 ] && rc=1 || rc=0; }  # CTest WILL_FAIL
  if [ $rc -eq 0 ]; then pass=$((pass+1)); echo "QNXTEST $n PASS rc=0 secs=$e"
  else fail=$((fail+1)); echo "QNXTEST $n FAIL rc=$rc secs=$e (see logs/$n.out)"; fi
}

# skipped CVE-2002-0059: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2004-0797: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2005-1849: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2005-2096: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-fixed-level-6: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-default-level-6: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-fixed-level-1: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-default-level-1: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-fixed-level-2: runs /usr/bin/cmake, not a test binary from the build
# skipped CVE-2018-25032-default-level-2: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-R: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-h: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-T: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-0: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-1: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-2: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-4: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-5: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-F: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-6: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-9: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-fireworks.jpg-f: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-R: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-h: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-T: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-0: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-1: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-2: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-4: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-5: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-F: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-6: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-9: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-lcet10.txt-f: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-R: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-h: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-T: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-0: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-1: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-2: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-4: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-5: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-F: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-6: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-9: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-paper-100k.pdf-f: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-detect-text-A: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-detect-binary-A: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-361: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-364: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-382: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-536-segfault: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-536-incomplete-read: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-536-zero-stored-block: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-751: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-1600-no-window-check: runs /usr/bin/cmake, not a test binary from the build
# skipped GH-1600-no-window-no-check: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-file_compress: runs /usr/bin/cmake, not a test binary from the build
# skipped minideflate-file_compress: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-help: runs /usr/bin/cmake, not a test binary from the build
# skipped minigzip-invalid: runs /usr/bin/cmake, not a test binary from the build
# skipped minideflate-help: runs /usr/bin/cmake, not a test binary from the build
# skipped minideflate-invalid: runs /usr/bin/cmake, not a test binary from the build
# skipped switchlevels-help: runs /usr/bin/cmake, not a test binary from the build
# skipped makecrct: runs /usr/bin/cmake, not a test binary from the build
# skipped makefixed: runs /usr/bin/cmake, not a test binary from the build
# skipped maketrees: runs /usr/bin/cmake, not a test binary from the build
run example 60 ./example
run infcover 60 ./infcover

echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"
[ $fail -eq 0 ]
