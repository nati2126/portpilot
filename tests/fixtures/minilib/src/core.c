/* core.c: library code QNX compiles. */
#include <sys/errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netdb.h>
#include <string.h>

#include "pollq.h"

#ifdef MINI_HAVE_EPOLL
#include <sys/epoll.h>
#endif

/* epoll_wait(fd, ...) in a comment is not a call */
static const char *note = "eventfd() in a string is not a call";

int mini_resolve_error(int rv)
{
	switch (rv) {
	case EAI_NONAME:
		return -1;
	default:
		return -2;
	}
}

int mini_listen(const char *path)
{
	struct sockaddr_un sun;
	int fd = socket(AF_UNIX, SOCK_STREAM, 0);
	memset(&sun, 0, sizeof(sun));
	strncpy(sun.sun_path, path, sizeof(sun.sun_path) - 1);
	if (connect(fd, (struct sockaddr *) &sun, sizeof(sun)) != 0 && errno == ECONNREFUSED) {
		return -1;
	}
	(void) note;
	return fd;
}
