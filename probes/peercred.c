// Probe: does getsockopt(LOCAL_PEERCRED) work on QNX for socketpair() fds vs connect()/accept() fds?
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/ucred.h>
#include <sys/un.h>
#include <unistd.h>
#ifndef SOL_LOCAL
#define SOL_LOCAL 0
#endif

static void q(const char *label, int fd) {
    struct xucred xu; socklen_t len = sizeof xu; memset(&xu, 0, sizeof xu);
    errno = 0;
    int rv = getsockopt(fd, SOL_LOCAL, LOCAL_PEERCRED, &xu, &len);
    int e = errno;
    printf("%-26s LOCAL_PEERCRED rv=%d errno=%d (%s) uid=%d", label, rv, e, strerror(e), (int)xu.cr_uid);
    uid_t u = 99; gid_t g = 99; errno = 0;
    rv = getpeereid(fd, &u, &g); e = errno;
    printf(" | getpeereid rv=%d errno=%d (%s) uid=%d\n", rv, e, strerror(e), (int)u);
}

int main(void) {
    int sp[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sp);
    q("socketpair", sp[0]);
    const char *p = "/tmp/pc.sock"; unlink(p);
    int l = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a; memset(&a, 0, sizeof a); a.sun_family = AF_UNIX; strcpy(a.sun_path, p);
    bind(l, (void *)&a, sizeof a); listen(l, 1);
    int c = socket(AF_UNIX, SOCK_STREAM, 0);
    connect(c, (void *)&a, sizeof a);
    int s = accept(l, NULL, NULL);
    q("connect() side", c);
    q("accept() side", s);
    printf("ENOTCONN=%d EINVAL=%d ENOPROTOOPT=%d  my uid=%d\n", ENOTCONN, EINVAL, ENOPROTOOPT, (int)getuid());
    unlink(p);
    return 0;
}
