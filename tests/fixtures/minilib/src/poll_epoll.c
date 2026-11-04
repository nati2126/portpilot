/* The epoll backend: CMake builds it only when MINI_HAVE_EPOLL passes. */
#include <sys/epoll.h>
#include <sys/eventfd.h>

int mini_poller_init(void)
{
	int ep = epoll_create1(0);
	int ev = eventfd(0, 0);
	return ep < 0 || ev < 0 ? -1 : 0;
}
