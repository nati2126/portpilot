# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/sp/transport/udp
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.sp.transport.udp.udp_tran_test "/work/nng/build/src/sp/transport/udp/udp_tran_test" "-t" "-v")
set_tests_properties(nng.sp.transport.udp.udp_tran_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.transport.udp.udp_wire_test "/work/nng/build/src/sp/transport/udp/udp_wire_test" "-t" "-v")
set_tests_properties(nng.sp.transport.udp.udp_wire_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
