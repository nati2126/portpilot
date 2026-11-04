#!/usr/bin/env bash
# F-011: which classic Linux link flags work with qcc for QNX 8.0? Host only, no target needed.
#   source ~/qnx800/qnxsdp-env.sh && probes/link_flags.sh
set -u
dir=$(mktemp -d)
cat > "$dir/t.c" <<'EOF'
#include <dlfcn.h>
#include <pthread.h>
#include <time.h>
int main(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return dlopen ? 0 : 1; }
EOF
for flag in "" -lpthread -lrt -ldl -pthread -latomic; do
  qcc -Vgcc_ntox86_64 "$dir/t.c" -o "$dir/t" $flag > "$dir/log" 2>&1
  printf '%-10s rc=%d %s\n' "${flag:-(none)}" $? "$(grep -m1 -oE 'cannot find.*' "$dir/log")"
done
