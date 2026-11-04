# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/sp
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.sp.pipe_test "/work/nng/build/src/sp/pipe_test" "-t" "-v")
set_tests_properties(nng.sp.pipe_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.device_test "/work/nng/build/src/sp/device_test" "-t" "-v")
set_tests_properties(nng.sp.device_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.multistress_test "/work/nng/build/src/sp/multistress_test" "-t" "-v")
set_tests_properties(nng.sp.multistress_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.nonblock_test "/work/nng/build/src/sp/nonblock_test" "-t" "-v")
set_tests_properties(nng.sp.nonblock_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.scalability_test "/work/nng/build/src/sp/scalability_test" "-t" "-v")
set_tests_properties(nng.sp.scalability_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.sp.reconnect_stress_test "/work/nng/build/src/sp/reconnect_stress_test" "-t" "-v")
set_tests_properties(nng.sp.reconnect_stress_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
subdirs("protocol")
subdirs("transport")
