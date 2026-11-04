// Probe: errno / EAI codes QNX returns in the 3 nng test failures (udp_tran, udp_test, ipc_test).
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static void gai(const char *host, int flags) {
    struct addrinfo h, *r = NULL;
    memset(&h, 0, sizeof h);
    h.ai_family = AF_UNSPEC; h.ai_socktype = SOCK_DGRAM; h.ai_flags = flags;
    int rv = getaddrinfo(host, "32", &h, &r);
    printf("getaddrinfo(%-14s flags=0x%x) rv=%d (%s)\n", host, flags, rv, rv ? gai_strerror(rv) : "ok");
    if (r) freeaddrinfo(r);
}

int main(void) {
    // 1. udp_tran: malformed address, dial (no AI_PASSIVE) vs listen (AI_PASSIVE)
    gai("127.0.0.1.32", AI_NUMERICSERV);
    gai("127.0.0.1.32", AI_NUMERICSERV | AI_PASSIVE);
    gai("127.0.x.1.32", AI_NUMERICSERV);
    gai("127.0.x.1.32", AI_NUMERICSERV | AI_PASSIVE);

    // 2. udp_test: sendmsg on a UDP/IPv4 socket with an AF_UNIX destination
    int u = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in sin; memset(&sin, 0, sizeof sin);
    sin.sin_family = AF_INET; sin.sin_addr.s_addr = htonl(0x7f000001);
    bind(u, (void *)&sin, sizeof sin);
    struct sockaddr_un sun; memset(&sun, 0, sizeof sun);
    sun.sun_family = AF_UNIX; strcpy(sun.sun_path, "/tmp/bogus");
    struct iovec iov = { .iov_base = "hi", .iov_len = 3 };
    struct msghdr m; memset(&m, 0, sizeof m);
    m.msg_name = &sun; m.msg_namelen = sizeof sun; m.msg_iov = &iov; m.msg_iovlen = 1;
    errno = 0;
    ssize_t n = sendmsg(u, &m, MSG_NOSIGNAL);
    printf("udp sendmsg to AF_UNIX: rv=%zd errno=%d (%s)  [EAFNOSUPPORT=%d EINVAL=%d]\n", n, errno, strerror(errno), EAFNOSUPPORT, EINVAL);
    close(u);

    // 3. ipc_test: connect() to a stale unix socket file (listener closed, file left behind)
    const char *p = "/tmp/stale.sock", *p2 = "/tmp/stale.sock.renamed";
    unlink(p); unlink(p2);
    int l = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a; memset(&a, 0, sizeof a); a.sun_family = AF_UNIX; strcpy(a.sun_path, p);
    printf("bind=%d listen=%d\n", bind(l, (void *)&a, sizeof a), listen(l, 5));
    printf("rename away=%d\n", rename(p, p2));
    close(l);
    printf("rename back=%d\n", rename(p2, p));
    for (int nb = 0; nb <= 1; nb++) {
        int c = socket(AF_UNIX, SOCK_STREAM, 0);
        if (nb) fcntl(c, F_SETFL, O_NONBLOCK);
        errno = 0;
        int rv = connect(c, (void *)&a, sizeof a);
        printf("connect stale (%s): rv=%d errno=%d (%s)  [ECONNREFUSED=%d ENOENT=%d]\n", nb ? "nonblock" : "block", rv, errno, strerror(errno), ECONNREFUSED, ENOENT);
        close(c);
    }
    int l2 = socket(AF_UNIX, SOCK_STREAM, 0);
    errno = 0;
    printf("rebind over stale file: rv=%d errno=%d (%s)\n", bind(l2, (void *)&a, sizeof a), errno, strerror(errno));
    // and the same sequence WITHOUT the rename dance
    const char *q = "/tmp/stale2.sock"; unlink(q);
    int l3 = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un b; memset(&b, 0, sizeof b); b.sun_family = AF_UNIX; strcpy(b.sun_path, q);
    bind(l3, (void *)&b, sizeof b); listen(l3, 5); close(l3);
    int c3 = socket(AF_UNIX, SOCK_STREAM, 0); fcntl(c3, F_SETFL, O_NONBLOCK); errno = 0;
    int rv3 = connect(c3, (void *)&b, sizeof b);
    printf("connect stale, no rename (nonblock): rv=%d errno=%d (%s)\n", rv3, errno, strerror(errno));
    unlink(p); unlink(q);
    return 0;
}
