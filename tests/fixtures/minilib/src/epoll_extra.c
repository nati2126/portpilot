/* Added through mini_sources_if(MINI_HAVE_EPOLL ...): not built on QNX. */
#include <sys/epoll.h>

int mini_extra(int fd)
{
	struct epoll_event ev;
	return epoll_ctl(fd, EPOLL_CTL_ADD, 0, &ev);
}
