# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/tools/perf
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.inproc_lat "/work/nng/build/src/tools/perf/inproc_lat" "64" "10000")
set_tests_properties(nng.inproc_lat PROPERTIES  TIMEOUT "30" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.inproc_thr "/work/nng/build/src/tools/perf/inproc_thr" "1400" "10000")
set_tests_properties(nng.inproc_thr PROPERTIES  TIMEOUT "30" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.pubdrop "/work/nng/build/src/tools/perf/pubdrop" "inproc://junk" "64" "1000" "2" "1")
set_tests_properties(nng.pubdrop PROPERTIES  _BACKTRACE_TRIPLES "/work/src")
