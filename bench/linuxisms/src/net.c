#include <sys/types.h>
#include <sys/socket.h>
#include "linuxisms.h"

/* Linux: MSG_MORE corks the socket until the next send without it. */
int lx_send_more(int fd, const void *buf, size_t len)
{
    return (int)send(fd, buf, len, MSG_MORE | MSG_NOSIGNAL);
}
