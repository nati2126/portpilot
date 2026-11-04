# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/supplemental/websocket
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.supplemental.sha1_test "/work/nng/build/src/supplemental/websocket/sha1_test" "-t" "-v")
set_tests_properties(nng.supplemental.sha1_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.supplemental.base64_test "/work/nng/build/src/supplemental/websocket/base64_test" "-t" "-v")
set_tests_properties(nng.supplemental.base64_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.supplemental.wssfile_test "/work/nng/build/src/supplemental/websocket/wssfile_test" "-t" "-v")
set_tests_properties(nng.supplemental.wssfile_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.supplemental.websocket_test "/work/nng/build/src/supplemental/websocket/websocket_test" "-t" "-v")
set_tests_properties(nng.supplemental.websocket_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
