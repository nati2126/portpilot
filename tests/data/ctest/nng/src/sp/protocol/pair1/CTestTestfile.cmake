# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/sp/protocol/pair1
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.sp.protocol.pair1.pair1_test "/work/nng/build/src/sp/protocol/pair1/pair1_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.pair1.pair1_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.protocol.pair1.pair1_poly_test "/work/nng/build/src/sp/protocol/pair1/pair1_poly_test" "-t" "-v")
set_tests_properties(nng.sp.protocol.pair1.pair1_poly_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
