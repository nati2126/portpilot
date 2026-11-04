#define _GNU_SOURCE
#include <string.h>
#include <stdlib.h>
#include "linuxisms.h"

char *lx_basename_dup(const char *path)
{
    char *copy = strdupa(path);
    const char *slash = strrchr(copy, '/');
    return strdup(slash ? slash + 1 : copy);
}
