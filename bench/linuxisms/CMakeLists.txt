cmake_minimum_required(VERSION 3.16)
project(linuxisms C)
# A small library written the way Linux code often is. Each file hits one Linux-only API
# that has no PortPilot rule, so the build errors on QNX must be fixed by the AI step.
option(LINUXISMS_TESTS "Build tests" ON)
add_library(linuxisms src/net.c src/dir.c src/proc.c src/str.c)
target_include_directories(linuxisms PUBLIC include)
if(LINUXISMS_TESTS)
  enable_testing()
  add_executable(linuxisms_test tests/test.c)
  target_link_libraries(linuxisms_test linuxisms)
  add_test(NAME linuxisms.all COMMAND linuxisms_test)
endif()
install(TARGETS linuxisms)
