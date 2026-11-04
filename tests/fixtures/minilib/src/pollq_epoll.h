#ifndef MINI_POLLQ_EPOLL_H
#define MINI_POLLQ_EPOLL_H
/* Only included when the epoll backend is selected: dead on QNX. */
#include <sys/epoll.h>
#define MINI_EV_HUP POLLHUP
#endif
