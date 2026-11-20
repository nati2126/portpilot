#!/bin/sh
# QNX test runner for paho.mqtt.c: 103 tests, generated from CTest by PortPilot.
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

run test1-1-single-thread-client 540 ./test1 --test_no 1 --connection tcp://localhost:1883
run test1-2-multithread-callbacks 540 ./test1 --test_no 2 --connection tcp://localhost:1883
run test1-3-connack-return-codes 540 ./test1 --test_no 3 --connection tcp://localhost:1883
run test1-4-client-persistence 540 ./test1 --test_no 4 --connection tcp://localhost:1883
run test1-5-disconnect-with-quiesce 540 ./test1 --test_no 5 --connection tcp://localhost:1883
run test1-6-connlost-will-message 540 ./test1 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test1-7-connlost-binary-will-message 540 ./test1 --test_no 7 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test1-1-ws-single-thread-client 540 ./test1 --test_no 1 --connection ws://localhost:1883
run test1-2-ws-multithread-callbacks 540 ./test1 --test_no 2 --connection ws://localhost:1883
run test1-3-ws-connack-return-codes 540 ./test1 --test_no 3 --connection ws://localhost:1883
run test1-4-ws-client-persistence 540 ./test1 --test_no 4 --connection ws://localhost:1883
run test1-5-ws-disconnect-with-quiesce 540 ./test1 --test_no 5 --connection ws://localhost:1883
run test1-6-ws-connlost-will-message 540 ./test1 --test_no 6 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test1-7-ws-connlost-binary-will-message 540 ./test1 --test_no 7 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-1-single-thread-client 540 ./test15 --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-2-multithread-callbacks 540 ./test15 --test_no 2 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-3-connack-return-codes 540 ./test15 --test_no 3 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-4-client-persistence 540 ./test15 --test_no 4 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-5-disconnect-with-quiesce 540 ./test15 --test_no 5 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-6-connlost-will-message 540 ./test15 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-7-connlost-binary-will-message 540 ./test15 --test_no 7 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-1-ws-single-thread-client 540 ./test15 --test_no 1 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-2-ws-multithread-callbacks 540 ./test15 --test_no 2 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-3-ws-connack-return-codes 540 ./test15 --test_no 3 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-4-ws-client-persistence 540 ./test15 --test_no 4 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-5-ws-disconnect-with-quiesce 540 ./test15 --test_no 5 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-6-ws-connlost-will-message 540 ./test15 --test_no 6 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test15-7-ws-connlost-binary-will-message 540 ./test15 --test_no 7 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test2-1-multiple-threads-single-client 540 ./test2 --connection tcp://localhost:1883
run test2-1-ws-multiple-threads-single-client 540 ./test2 --connection ws://localhost:1883
run test4-1-basic-connect-subscribe-receive 540 ./test4 --test_no 1 --connection tcp://localhost:1883
run test4-2-connect-timeout 540 ./test4 --test_no 2 --connection tcp://localhost:1883
run test4-3-multiple-client-objs-simultaneous-working 540 ./test4 --test_no 3 --connection tcp://localhost:1883
run test4-4-send-receive-big-messages 540 ./test4 --test_no 4 --connection tcp://localhost:1883
run test4-5-connack-return-codes 540 ./test4 --test_no 5 --connection tcp://localhost:1883
run test4-6-ha-connections 540 ./test4 --test_no 6 --connection tcp://localhost:1883
run test4-7-pending-tokens 540 ./test4 --test_no 7 --connection tcp://localhost:1883
run test4-8-incomplete-commands-requests 540 ./test4 --test_no 8 --connection tcp://localhost:1883
run test45-1-basic-connect-subscribe-receive 540 ./test45 --test_no 1 --connection tcp://localhost:1883
run test45-2-connect-timeout 540 ./test45 --test_no 2 --connection tcp://localhost:1883
run test45-3-multiple-client-objs-simultaneous-working 540 ./test45 --test_no 3 --connection tcp://localhost:1883
run test45-4-send-receive-big-messages 540 ./test45 --test_no 4 --connection tcp://localhost:1883
run test45-5-connack-return-codes 540 ./test45 --test_no 5 --connection tcp://localhost:1883
run test45-6-ha-connections 540 ./test45 --test_no 6 --connection tcp://localhost:1883
run test45-7-pending-tokens 540 ./test45 --test_no 7 --connection tcp://localhost:1883
run test45-8-incomplete-commands-requests 540 ./test45 --test_no 8 --connection tcp://localhost:1883
run test6-restart-recovery 540 ./test6 --connection tcp://localhost:1883
run test8-1-basic-connect-subscribe-receive 540 ./test8 --test_no 1 --connection tcp://localhost:1883
run test8-2-connect-timeout 540 ./test8 --test_no 2 --connection tcp://localhost:1883
run test8-3-multiple-client-objects-simultaneous-working 540 ./test8 --test_no 3 --connection tcp://localhost:1883
run test8-4-send-receive-big-messages 540 ./test8 --test_no 4 --connection tcp://localhost:1883 --size 500000
run test8-5a-all-ha-connections-out-of-service 540 ./test8 --test_no 5 --connection tcp://localhost:1883
run test8-5b-all-ha-connections-out-of-service-except-the-last-one 540 ./test8 --test_no 6 --connection tcp://localhost:1883
run test8-5c-all-ha-connections-out-of-service-except-the-first-one 540 ./test8 --test_no 7 --connection tcp://localhost:1883
run test8-6-blocked-acks 540 ./test8 --test_no 8 --connection tcp://localhost:1883 --size 500000
run test9-1-offline-buffering-send-disconnected 540 ./test9 --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-2-offline-buffering-send-disconnected-serverURIs 540 ./test9 --test_no 2 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-3-offline-buffering-auto-reconnect 540 ./test9 --test_no 3 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-4-offline-buffering-auto-reconnect-serverURIs 540 ./test9 --test_no 4 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-5-offline-buffering-max-buffered 540 ./test9 --test_no 5 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-6-offline-buffering-max-buffered-binary-will 540 ./test9 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-8-offline-buffering-before-connect 540 ./test9 --test_no 8 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-10-offline-buffering-delete-oldest-messages 540 ./test9 --test_no 10 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-1-ws-offline-buffering-send-disconnected 540 ./test9 --test_no 1 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-2-ws-offline-buffering-send-disconnected-serverURIs 540 ./test9 --test_no 2 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-3-ws-offline-buffering-auto-reconnect 540 ./test9 --test_no 3 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-4-ws-offline-buffering-auto-reconnect-serverURIs 540 ./test9 --test_no 4 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-5-ws-offline-buffering-max-buffered 540 ./test9 --test_no 5 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-6-ws-offline-buffering-max-buffered-binary-will 540 ./test9 --test_no 6 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-8-ws-offline-buffering-before-connect 540 ./test9 --test_no 8 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test9-10-ws-offline-buffering-delete-oldest-messages 540 ./test9 --test_no 10 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-1-offline-buffering-send-disconnected 540 ./test95 --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-2-offline-buffering-send-disconnected-serverURIs 540 ./test95 --test_no 2 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-3-offline-buffering-auto-reconnect 540 ./test95 --test_no 3 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-4-offline-buffering-auto-reconnect-serverURIs 540 ./test95 --test_no 4 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-5-offline-buffering-max-buffered 540 ./test95 --test_no 5 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-6-offline-buffering-max-buffered-binary-will 540 ./test95 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-1ws-offline-buffering-send-disconnected 540 ./test95 --test_no 1 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-2ws-offline-buffering-send-disconnected-serverURIs 540 ./test95 --test_no 2 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-3ws-offline-buffering-auto-reconnect 540 ./test95 --test_no 3 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-4ws-offline-buffering-auto-reconnect-serverURIs 540 ./test95 --test_no 4 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-5ws-offline-buffering-max-buffered 540 ./test95 --test_no 5 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test95-6ws-offline-buffering-max-buffered-binary-will 540 ./test95 --test_no 6 --connection ws://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-1-client_topic_aliases 540 ./test10 --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-2-server_topic_aliases 540 ./test10 --test_no 2 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-3-subscription_ids 540 ./test10 --test_no 3 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-4-flow_control 540 ./test10 --test_no 4 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-5-error_handling 540 ./test10 --test_no 5 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-6-qos_1_2_errors 540 ./test10 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-7-request_response 540 ./test10 --test_no 7 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-8-subscribe_options 540 ./test10 --test_no 8 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test10-9-shared_subscriptions 540 ./test10 --test_no 9 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-1-client_topic_aliases 540 ./test11 --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-2-server_topic_aliases 540 ./test11 --test_no 2 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-3-subscription_ids 540 ./test11 --test_no 3 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-4-flow_control 540 ./test11 --test_no 4 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-5-error_handling 540 ./test11 --test_no 5 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-6-qos_1_2_errors 540 ./test11 --test_no 6 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-7-request_response 540 ./test11 --test_no 7 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-8-subscribe_options 540 ./test11 --test_no 8 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test11-9-shared_subscriptions 540 ./test11 --test_no 9 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test_sync_session_present-1-client_session_present_after_reconnect 540 ./test_sync_session_present --test_no 1 --connection tcp://localhost:1883 --proxy_connection tcp://localhost:1884
run test_connect_destroy-1-execute-destroy-during-connect 540 ./test_connect_destroy --test_no 1 --connection tcp://localhost:1883

echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"
[ $fail -eq 0 ]
