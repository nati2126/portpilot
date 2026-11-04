// Probe: after the write end of a pipe is closed, does poll() on the read end report POLLHUP? (nng shutdown relies on it)
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

static void show(const char *label, int rfd) {
    struct pollfd p = { .fd = rfd, .events = POLLIN, .revents = 0 };
    int n = poll(&p, 1, 500);
    char b[8]; ssize_t r = read(rfd, b, sizeof b);
    printf("%-38s poll=%d revents=0x%03x [%s%s%s%s] read()=%zd\n", label, n, p.revents,
           (p.revents & POLLIN) ? "IN " : "", (p.revents & POLLHUP) ? "HUP " : "",
           (p.revents & POLLERR) ? "ERR " : "", (p.revents & POLLNVAL) ? "NVAL" : "", r);
}

int main(void) {
    int p[2];
    pipe(p); fcntl(p[0], F_SETFL, O_NONBLOCK); close(p[1]);
    show("pipe: writer closed, empty", p[0]);
    pipe(p); fcntl(p[0], F_SETFL, O_NONBLOCK); write(p[1], "x", 1); close(p[1]);
    show("pipe: writer closed, 1 byte pending", p[0]);
    show("  ...same fd polled again after drain", p[0]);
    int s[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, s); fcntl(s[0], F_SETFL, O_NONBLOCK); close(s[1]);
    show("socketpair: peer closed, empty", s[0]);
    socketpair(AF_UNIX, SOCK_STREAM, 0, s); fcntl(s[0], F_SETFL, O_NONBLOCK); write(s[1], "x", 1); close(s[1]);
    show("socketpair: peer closed, 1 byte pending", s[0]);
    show("  ...same fd polled again after drain", s[0]);
    return 0;
}
