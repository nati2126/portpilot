#define _GNU_SOURCE
#include <unistd.h>
#include <sys/syscall.h>
#include "linuxisms.h"

long lx_thread_id(void)
{
    return (long)syscall(SYS_gettid);
}
