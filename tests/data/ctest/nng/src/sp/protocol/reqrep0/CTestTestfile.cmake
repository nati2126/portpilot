# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/sp/protocol/reqrep0
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.sp.protocol.reqrep0.req_test "/work/nng/build/src/sp/protocol/reqrep0/req_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.reqrep0.req_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.reqrep0.rep_test "/work/nng/build/src/sp/protocol/reqrep0/rep_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.reqrep0.rep_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.reqrep0.xrep_test "/work/nng/build/src/sp/protocol/reqrep0/xrep_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.reqrep0.xrep_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.reqrep0.xreq_test "/work/nng/build/src/sp/protocol/reqrep0/xreq_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.reqrep0.xreq_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.reqrep0.reqstress_test "/work/nng/build/src/sp/protocol/reqrep0/reqstress_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.reqrep0.reqstress_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
