#ifndef MINI_PLATFORM_H
#define MINI_PLATFORM_H

/* Platform detection through the project's own macros (efsw style). */
#define MINI_OS_WIN 1
#define MINI_OS_LINUX 2
#define MINI_OS_OTHER 3

#if defined(_WIN32)
#define MINI_OS MINI_OS_WIN
#elif defined(__linux__)
#define MINI_OS MINI_OS_LINUX
#elif defined(__SVR4)
#define MINI_OS MINI_OS_OTHER
#else
#define MINI_OS MINI_OS_OTHER
#endif

#ifndef MINI_USE_FANCY
#define MINI_USE_FANCY 0
#endif

#endif
