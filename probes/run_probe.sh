#!/usr/bin/env bash
# Build one probe for QNX 8.0 x86_64 and run it on a QNX target over SSH.
#
#   probes/run_probe.sh <name> [extra qcc args]      e.g.  probes/run_probe.sh pipe_pollhup -lsocket
#
# Needs: the QNX SDP environment (source qnxsdp-env.sh) and a running target.
#   QNX_IP   target address (required)
#   QNX_KEY  SSH private key (optional)
set -euo pipefail
name=$1; shift
here=$(cd "$(dirname "$0")" && pwd)
: "${QNX_IP:?set QNX_IP to the target address}"
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)
[ -n "${QNX_KEY:-}" ] && ssh_opts+=(-i "$QNX_KEY")
out=$(mktemp -d)/"$name"
qcc -Vgcc_ntox86_64 -O1 -o "$out" "$here/$name.c" "$@"
scp "${ssh_opts[@]}" -q "$out" "root@$QNX_IP:/tmp/$name"
ssh "${ssh_opts[@]}" "root@$QNX_IP" "/tmp/$name"
