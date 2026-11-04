#ifndef LINUXISMS_H
#define LINUXISMS_H
#include <stddef.h>
int lx_send_more(int fd, const void *buf, size_t len);  /* MSG_MORE */
int lx_count_subdirs(const char *path);                  /* struct dirent d_type */
long lx_thread_id(void);                                 /* gettid() */
char *lx_basename_dup(const char *path);                 /* GNU basename(), strdupa */
#endif
