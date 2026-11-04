# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/sp/protocol/pubsub0
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.sp.protocol.pubsub0.pub_test "/work/nng/build/src/sp/protocol/pubsub0/pub_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.pubsub0.pub_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.pubsub0.sub_test "/work/nng/build/src/sp/protocol/pubsub0/sub_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.pubsub0.sub_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.pubsub0.xsub_test "/work/nng/build/src/sp/protocol/pubsub0/xsub_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.pubsub0.xsub_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
