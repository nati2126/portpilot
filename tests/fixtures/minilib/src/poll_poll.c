/* The poll backend: QNX builds this one. */
#include <poll.h>
#include <unistd.h>

int mini_poller_wait(struct pollfd *fds, int n)
{
	int rv = poll(fds, n, -1);
	if (rv > 0 && (fds[0].revents & POLLHUP)) {
		return -1;
	}
	return rv;
}
