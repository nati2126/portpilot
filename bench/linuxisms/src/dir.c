#include <dirent.h>
#include <string.h>
#include "linuxisms.h"

int lx_count_subdirs(const char *path)
{
    DIR *d = opendir(path);
    struct dirent *e;
    int n = 0;
    if (!d)
        return -1;
    while ((e = readdir(d)) != NULL) {
        if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0)
            continue;
        if (e->d_type == DT_DIR)
            n++;
    }
    closedir(d);
    return n;
}
