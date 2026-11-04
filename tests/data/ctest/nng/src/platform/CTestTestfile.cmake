# CMake generated Testfile for 
# Source directory: /work/src
# Build directory: /work/nng/build/src/platform
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(nng.platform.files_test "/work/nng/build/src/platform/files_test" "-t" "-v")
set_tests_properties(nng.platform.files_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.platform.ipc_stream_test "/work/nng/build/src/platform/ipc_stream_test" "-t" "-v")
set_tests_properties(nng.platform.ipc_stream_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.platform.platform_test "/work/nng/build/src/platform/platform_test" "-t" "-v")
set_tests_properties(nng.platform.platform_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.platform.resolver_test "/work/nng/build/src/platform/resolver_test" "-t" "-v")
set_tests_properties(nng.platform.resolver_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.platform.tcp_stream_test "/work/nng/build/src/platform/tcp_stream_test" "-t" "-v")
set_tests_properties(nng.platform.tcp_stream_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
add_test(nng.platform.udp_test "/work/nng/build/src/platform/udp_test" "-t" "-v")
set_tests_properties(nng.platform.udp_test PROPERTIES  TIMEOUT "180" _BACKTRACE_TRIPLES "/work/src")
subdirs("posix")
subdirs("windows")
