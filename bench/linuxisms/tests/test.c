#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "linuxisms.h"

#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); return 1; } } while (0)

int main(void)
{
    char tmpl[] = "/tmp/lxtestXXXXXX";
    char path[256];
    char *b;
    CHECK(mkdtemp(tmpl) != NULL);
    snprintf(path, sizeof path, "%s/a", tmpl); CHECK(mkdir(path, 0700) == 0);
    snprintf(path, sizeof path, "%s/b", tmpl); CHECK(mkdir(path, 0700) == 0);
    snprintf(path, sizeof path, "%s/f", tmpl); fclose(fopen(path, "w"));
    CHECK(lx_count_subdirs(tmpl) == 2);
    CHECK(lx_thread_id() > 0);
    b = lx_basename_dup("/usr/lib/libz.so");
    CHECK(b && strcmp(b, "libz.so") == 0);
    free(b);
    printf("PASS\n");
    return 0;
}
