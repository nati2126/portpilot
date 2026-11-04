#ifndef MINI_POLLQ_H
#define MINI_POLLQ_H

#if defined(MINI_POLLQ_EPOLL)
#include "pollq_epoll.h"
#elif defined(MINI_POLLQ_POLL)
#include "pollq_poll.h"
#else
#error "no poller"
#endif

#endif
