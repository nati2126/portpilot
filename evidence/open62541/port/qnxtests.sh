#!/bin/sh
# QNX test runner for open62541: 146 tests, generated from CTest by PortPilot.
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

# skipped test_generate_datatypes_cross_ns: runs /usr/bin/python3, not a test binary from the build
# skipped test_nodeset_compiler_regressions: runs /usr/bin/python3, not a test binary from the build
run check_types_builtin 60 ./check_types_builtin
run check_ziptree 60 ./check_ziptree
run check_mp_printf 60 ./check_mp_printf
run check_base64 60 ./check_base64
run check_dtoa 60 ./check_dtoa
run check_itoa 60 ./check_itoa
run check_libc_time 60 ./check_libc_time
run check_parse_num 60 ./check_parse_num
run check_pcg_basic 60 ./check_pcg_basic
run check_utf8 60 ./check_utf8
run check_musl_inet_pton 60 ./check_musl_inet_pton
run check_config_default 60 ./check_config_default
run check_log_syslog 60 ./check_log_syslog
run check_cj5 60 ./check_cj5
run check_types_builtin_json 60 ./check_types_builtin_json
run check_types_json_encode 60 ./check_types_json_encode
run check_types_json_decode 60 ./check_types_json_decode
run check_json_config 60 ./check_json_config
run check_pubsub_encoding_json 60 ./check_pubsub_encoding_json
run check_pubsub_publish_json 60 ./check_pubsub_publish_json
run check_yxml 60 ./check_yxml
run check_types_builtin_xml 60 ./check_types_builtin_xml
run check_xml_encoding_roundtrip 60 ./check_xml_encoding_roundtrip
run check_types_memory 60 ./check_types_memory
run check_types_range 60 ./check_types_range
run check_types_parse 60 ./check_types_parse
run check_eventfilter_parser 60 ./check_eventfilter_parser
run check_types_custom 60 ./check_types_custom
run check_chunking 60 ./check_chunking
run check_utils 60 ./check_utils
run check_kvm_utils 60 ./check_kvm_utils
run check_util_functions 60 ./check_util_functions
run check_types_nodeid_copy 60 ./check_types_nodeid_copy
run check_types_builtin_variant 60 ./check_types_builtin_variant
run check_types_range_lookup 60 ./check_types_range_lookup
run check_types_order 60 ./check_types_order
run check_types_order_struct 60 ./check_types_order_struct
run check_utils_trustlist_path 60 ./check_utils_trustlist_path
run check_types_copy_complex 60 ./check_types_copy_complex
run check_types_print 60 ./check_types_print
run check_types_definition 60 ./check_types_definition
run check_types_namespace_mapping 60 ./check_types_namespace_mapping
run check_types_allocation_failures 60 ./check_types_allocation_failures
run check_encoding_roundtrip 60 ./check_encoding_roundtrip
run check_types_builtin_binary 60 ./check_types_builtin_binary
run check_utils_url_kvm 60 ./check_utils_url_kvm
run check_securechannel 60 ./check_securechannel
run check_securechannel_unit 60 ./check_securechannel_unit
run check_timer 60 ./check_timer
run check_eventloop 60 ./check_eventloop
run check_eventloop_tcp 60 ./check_eventloop_tcp
run check_eventloop_udp 60 ./check_eventloop_udp
run check_server_config_json 60 ./check_server_config_json
run check_accesscontrol 60 ./check_accesscontrol
run check_services_view 60 ./check_services_view
run check_services_attributes 60 ./check_services_attributes
run check_services_nodemanagement 60 ./check_services_nodemanagement
run check_discovery_coverage 60 ./check_discovery_coverage
run check_server_callbacks 60 ./check_server_callbacks
run check_server_password 60 ./check_server_password
run check_mt_shutdown 60 ./check_mt_shutdown
run check_mt_addVariableNode 60 ./check_mt_addVariableNode
run check_mt_addVariableTypeNode 60 ./check_mt_addVariableTypeNode
run check_mt_addObjectNode 60 ./check_mt_addObjectNode
run check_mt_readValueAttribute 60 ./check_mt_readValueAttribute
run check_mt_writeValueAttribute 60 ./check_mt_writeValueAttribute
run check_mt_readWriteDelete 60 ./check_mt_readWriteDelete
run check_mt_readWriteDeleteCallback 60 ./check_mt_readWriteDeleteCallback
run check_mt_addDeleteObject 60 ./check_mt_addDeleteObject
run check_server_asyncop 60 ./check_server_asyncop
run check_services_call 60 ./check_services_call
run check_services_method_coverage 60 ./check_services_method_coverage
run check_services_subscriptions 60 ./check_services_subscriptions
run check_subscription_publishqueue 60 ./check_subscription_publishqueue
run check_monitoreditem_filter 60 ./check_monitoreditem_filter
run check_subscription_events 60 ./check_subscription_events
run check_subscription_events_local 60 ./check_subscription_events_local
run check_subscription_event_filter 60 ./check_subscription_event_filter
run check_nodestore 60 ./check_nodestore
run check_server_historical_data 60 ./check_server_historical_data
run check_server_historical_data_circular 60 ./check_server_historical_data_circular
run check_session 60 ./check_session
run check_session_errorpaths 60 ./check_session_errorpaths
run check_session_authtoken_rng 60 ./check_session_authtoken_rng
run check_server 60 ./check_server
run check_server_utils_coverage 60 ./check_server_utils_coverage
run check_services_securechannel 60 ./check_services_securechannel
run check_server_auditing 60 ./check_server_auditing
run check_server_jobs 60 ./check_server_jobs
run check_server_userspace 60 ./check_server_userspace
run check_node_inheritance 60 ./check_node_inheritance
run check_server_utils 60 ./check_server_utils
run check_nodes 60 ./check_nodes
run check_server_diagnostics 60 ./check_server_diagnostics
run check_server_readwrite 60 ./check_server_readwrite
run check_server_attr_wrappers 60 ./check_server_attr_wrappers
run check_services_nodemanagement_callbacks 60 ./check_services_nodemanagement_callbacks
run check_server_ns0_diagnostics 60 ./check_server_ns0_diagnostics
run check_server_node_services 60 ./check_server_node_services
run check_server_client_readwrite 60 ./check_server_client_readwrite
run check_services_attributes_all 60 ./check_services_attributes_all
run check_services_subscriptions_modify 60 ./check_services_subscriptions_modify
run check_local_monitored_item 60 ./check_local_monitored_item
run check_datachange_deadband_typekinds 60 ./check_datachange_deadband_typekinds
run check_pubsub_encoding 60 ./check_pubsub_encoding
run check_pubsub_encoding_custom 60 ./check_pubsub_encoding_custom
run check_pubsub_pds 60 ./check_pubsub_pds
run check_pubsub_state_machine 60 ./check_pubsub_state_machine
run check_pubsub_state_machine_extra 60 ./check_pubsub_state_machine_extra
run check_pubsub_connection_udp 60 ./check_pubsub_connection_udp
run check_pubsub_publish 60 ./check_pubsub_publish
run check_pubsub_get_state 60 ./check_pubsub_get_state
run check_pubsub_udp_unicast 60 ./check_pubsub_udp_unicast
run check_pubsub_publisherid 60 ./check_pubsub_publisherid
run check_pubsub_subscribe 60 ./check_pubsub_subscribe
run check_pubsub_publishspeed 60 ./check_pubsub_publishspeed
run check_pubsub_offset 60 ./check_pubsub_offset
run check_pubsub_custom_state_machine 60 ./check_pubsub_custom_state_machine
run check_pubsub_subscribe_msgrcvtimeout 60 ./check_pubsub_subscribe_msgrcvtimeout
run check_pubsub_informationmodel 60 ./check_pubsub_informationmodel
run check_pubsub_informationmodel_methods 60 ./check_pubsub_informationmodel_methods
run check_server_readspeed 60 ./check_server_readspeed
run check_server_speed_addnodes 60 ./check_server_speed_addnodes
run check_server_monitoringspeed 60 ./check_server_monitoringspeed
run check_server_reverseconnect 60 ./check_server_reverseconnect
run check_client 60 ./check_client
run check_client_config_coverage 60 ./check_client_config_coverage
run check_client_lifecycle_coverage 60 ./check_client_lifecycle_coverage
run check_client_discovery 60 ./check_client_discovery
run check_activateSession 60 ./check_activateSession
run check_activateSessionAsync 60 ./check_activateSessionAsync
run check_client_securechannel 60 ./check_client_securechannel
run check_client_async 60 ./check_client_async
run check_client_async_read 60 ./check_client_async_read
run check_client_async_connect 60 ./check_client_async_connect
run check_client_highlevel 60 ./check_client_highlevel
run check_client_highlevel_read 60 ./check_client_highlevel_read
run check_client_highlevel_write 60 ./check_client_highlevel_write
run check_client_highlevel_readwrite 60 ./check_client_highlevel_readwrite
run check_client_subscriptions 60 ./check_client_subscriptions
run check_client_subscriptions_datachange 60 ./check_client_subscriptions_datachange
run check_subscriptionWithactivateSession 60 ./check_subscriptionWithactivateSession
run check_client_reconnect 60 ./check_client_reconnect
run check_client_historical_data 60 ./check_client_historical_data
run check_certificategroup_none 60 ./check_certificategroup_none
run check_nodeset_value_mapping 60 ./check_nodeset_value_mapping

echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"
[ $fail -eq 0 ]
