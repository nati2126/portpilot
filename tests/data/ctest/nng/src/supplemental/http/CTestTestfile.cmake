# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/supplemental/http
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.supplemental.http_client_test "/work/nng/build/src/supplemental/http/http_client_test" "-t" "-v")
set_tests_properties(nng.supplemental.http_client_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.supplemental.http_server_test "/work/nng/build/src/supplemental/http/http_server_test" "-t" "-v")
set_tests_properties(nng.supplemental.http_server_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
