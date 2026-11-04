// Probe: does O_NONBLOCK set via fcntl(F_SETFL) work on QNX pipes?  (nng nni_plat_pipe_* pattern)
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static void on_alarm(int s) { (void)s; static const char m[] = "  -> read() BLOCKED (alarm fired)\n"; write(2, m, sizeof m - 1); }

static void drain_test(const char *label, int rfd, int wfd) {
    int fl = fcntl(rfd, F_GETFL);
    printf("%s: F_GETFL=0x%x O_NONBLOCK(0x%x) set=%s\n", label, fl, O_NONBLOCK, (fl >= 0 && (fl & O_NONBLOCK)) ? "yes" : "NO");
    char c = 1, buf[32];
    write(wfd, &c, 1);
    ssize_t n1 = read(rfd, buf, sizeof buf);
    int e1 = errno;
    alarm(2);
    errno = 0;
    ssize_t n2 = read(rfd, buf, sizeof buf);   // pipe now empty: must return -1/EAGAIN if non-blocking
    int e2 = errno;
    alarm(0);
    printf("  first read=%zd (%s)  second read=%zd errno=%d (%s)\n", n1, n1 < 0 ? strerror(e1) : "ok", n2, e2, strerror(e2));
}

int main(void) {
    struct sigaction sa; memset(&sa, 0, sizeof sa); sa.sa_handler = on_alarm; sigaction(SIGALRM, &sa, NULL);  // no SA_RESTART
    int p[2];
    if (pipe(p) == 0) {
        int r0 = fcntl(p[0], F_SETFL, O_NONBLOCK), r1 = fcntl(p[1], F_SETFL, O_NONBLOCK);
        printf("pipe(): fcntl(F_SETFL,O_NONBLOCK) rc=%d,%d errno=%d (%s)\n", r0, r1, errno, strerror(errno));
        drain_test("pipe+fcntl", p[0], p[1]);
    }
    int q[2];
    if (pipe(q) == 0) {
        int fl = fcntl(q[0], F_GETFL);
        int r = fcntl(q[0], F_SETFL, fl | O_NONBLOCK); fcntl(q[1], F_SETFL, fcntl(q[1], F_GETFL) | O_NONBLOCK);
        printf("pipe(): F_SETFL(GETFL|O_NONBLOCK) rc=%d\n", r);
        drain_test("pipe+fcntl(getfl|nb)", q[0], q[1]);
    }
    int s[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, s) == 0) {
        fcntl(s[0], F_SETFL, O_NONBLOCK); fcntl(s[1], F_SETFL, O_NONBLOCK);
        drain_test("socketpair+fcntl", s[0], s[1]);
    } else printf("socketpair failed: %s\n", strerror(errno));
    return 0;
}
