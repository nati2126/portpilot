// Probe: cost of one 4-byte read() from /dev/urandom on QNX (nng's nni_random fallback), vs 4 KiB reads.
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

int main(void) {
    int fd = open("/dev/urandom", O_RDONLY);
    uint32_t v; static char big[4096];
    const int N = 100000;
    double t0 = now();
    for (int i = 0; i < N; i++) read(fd, &v, sizeof v);
    double t1 = now();
    for (int i = 0; i < N / 1024 * 4; i++) read(fd, big, sizeof big);   // same total bytes
    double t2 = now();
    printf("4-byte reads : %d calls, %.3f s, %.2f us/call\n", N, t1 - t0, (t1 - t0) / N * 1e6);
    printf("4 KiB reads  : %d calls, %.3f s (same %d bytes)\n", N / 1024 * 4, t2 - t1, N * 4);
    printf("extrapolated nuts_tran_huge_msg (5 x 1 MiB, 1 call/byte): %.0f s\n", (t1 - t0) / N * 5 * 1048576);
    return 0;
}
