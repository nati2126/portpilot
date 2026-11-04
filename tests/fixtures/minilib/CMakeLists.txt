# Fixture: a small library shaped like nng (wrapper check functions, a poller chosen by
# configure checks, a platform chain with a QNX branch, an optional TLS directory).
cmake_minimum_required(VERSION 3.15)
project(minilib C CXX)

include(CheckSymbolExists)
include(CheckFunctionExists)
include(CheckLibraryExists)

option(MINI_TESTS "Build tests" ON)
option(MINI_ENABLE_TLS "Enable TLS" OFF)
set(MINI_POLLER "auto" CACHE STRING "Poller")

function(mini_check_sym SYM HDRS DEF)
    check_symbol_exists(${SYM} "${HDRS}" ${DEF})
    if (${DEF})
        target_compile_definitions(mini PRIVATE ${DEF}=1)
    endif ()
endfunction()

function(mini_check_lib LIB SYM DEF)
    check_library_exists(${LIB} ${SYM} "" ${DEF})
endfunction()

function(mini_defines)
    target_compile_definitions(mini PRIVATE ${ARGN})
endfunction()

function(mini_sources_if COND)
    foreach (f ${ARGN})
        if (${COND})
            target_sources(mini PRIVATE ${f})
        endif ()
    endforeach ()
endfunction()

add_library(mini src/core.c src/win.c src/obj.cpp)

if (CMAKE_SYSTEM_NAME MATCHES "Linux")
    mini_defines(MINI_PLATFORM_LINUX)
    target_link_libraries(mini pthread)
elseif (CMAKE_SYSTEM_NAME MATCHES "QNX")
    mini_defines(MINI_PLATFORM_QNX)
else ()
    mini_defines(MINI_PLATFORM_OTHER)
endif ()

mini_check_sym(epoll_create sys/epoll.h MINI_HAVE_EPOLL)
mini_check_sym(AF_INET6 netinet/in.h MINI_HAVE_INET6)
mini_check_sym(poll poll.h MINI_HAVE_POLL)
check_function_exists(recvmsg MINI_HAVE_RECVMSG)
check_function_exists(strlcpy MINI_HAVE_STRLCPY)
mini_check_lib(pthread sem_wait MINI_HAVE_SEM_PTHREAD)

if (MINI_POLLER STREQUAL "epoll")
    set(MINI_POLLQ_EPOLL ON)
elseif (MINI_POLLER STREQUAL "poll")
    set(MINI_POLLQ_POLL ON)
else ()
    if (MINI_HAVE_EPOLL)
        set(MINI_POLLQ_EPOLL ON)
    elseif (MINI_HAVE_POLL)
        set(MINI_POLLQ_POLL ON)
    endif ()
endif ()

if (MINI_POLLQ_EPOLL)
    mini_defines(MINI_POLLQ_EPOLL)
    target_sources(mini PRIVATE src/poll_epoll.c)
elseif (MINI_POLLQ_POLL)
    mini_defines(MINI_POLLQ_POLL)
    target_sources(mini PRIVATE src/poll_poll.c)
endif ()

mini_sources_if(MINI_HAVE_EPOLL src/epoll_extra.c)

if (MINI_ENABLE_TLS)
    add_subdirectory(src/tls)
endif ()

if (MINI_TESTS)
    add_executable(fork_test tests/fork_test.c)
endif ()
