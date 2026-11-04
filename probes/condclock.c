// Probe: does pthread_cond_timedwait honor pthread_condattr_setclock(CLOCK_MONOTONIC) on QNX?
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static double now(clockid_t c) { struct timespec t; clock_gettime(c, &t); return t.tv_sec + t.tv_nsec / 1e9; }

static void trial(const char *label, int setclock, clockid_t cid) {
    pthread_condattr_t a; pthread_cond_t cv; pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
    pthread_condattr_init(&a);
    int rs = setclock ? pthread_condattr_setclock(&a, cid) : 0;
    pthread_cond_init(&cv, &a);
    struct timespec dl; clock_gettime(cid, &dl);
    dl.tv_nsec += 200 * 1000000L; if (dl.tv_nsec >= 1000000000L) { dl.tv_sec++; dl.tv_nsec -= 1000000000L; }
    double t0 = now(CLOCK_MONOTONIC);
    pthread_mutex_lock(&m);
    int rv = pthread_cond_timedwait(&cv, &m, &dl);
    pthread_mutex_unlock(&m);
    printf("%-34s setclock_rc=%d timedwait_rc=%d (%s) waited=%.3fs\n", label, rs, rv, strerror(rv), now(CLOCK_MONOTONIC) - t0);
}

int main(void) {
    printf("CLOCK_MONOTONIC=%.3f  CLOCK_REALTIME=%.3f\n", now(CLOCK_MONOTONIC), now(CLOCK_REALTIME));
    trial("monotonic attr + monotonic deadline", 1, CLOCK_MONOTONIC);
    trial("realtime attr + realtime deadline", 1, CLOCK_REALTIME);
    trial("default attr + realtime deadline", 0, CLOCK_REALTIME);
    struct timespec s = {0, 200000000L}; double t0 = now(CLOCK_MONOTONIC); int r = nanosleep(&s, &s);
    printf("nanosleep(200ms) rc=%d waited=%.3fs\n", r, now(CLOCK_MONOTONIC) - t0);
    return 0;
}
