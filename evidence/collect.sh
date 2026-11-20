#!/bin/sh
# Copy the outputs of real `portpilot port` runs into evidence/: the generated port (text
# files only, no build tree), report.html, and the test output recorded on the QNX target.
# usage: evidence/collect.sh RUNS_DIR [TARGET_IP]   (RUNS_DIR holds one folder per library)
set -eu
runs=$1
ip=${2:-}
ev=$(cd "$(dirname "$0")" && pwd)
key=${QNX_KEY:-$HOME/.ssh/qnx_vm_ed25519}
kh=${QNX_KNOWN_HOSTS:-$HOME/qnx-work/known_hosts}
home_re=$(printf '%s' "$HOME" | sed 's/[.[\*^$/]/\\&/g')
clean() { sed -i "s/$home_re/~/g" "$@"; }  # no host user paths in the repo

for run in "$runs"/*/; do
  lib=$(basename "$run")
  [ -f "$run/run.json" ] || continue
  t=$(ls -d "$run"/logs/tests-* 2>/dev/null | sort -V | tail -n1) || true
  # only libraries whose QNX test run finished
  [ -n "$t" ] && grep -q "^QNXTEST " "$t/qnxtests.out" 2>/dev/null && [ -d "$t/target-logs" ] ||
    continue
  out=$ev/$lib
  rm -rf "$out"; mkdir -p "$out/port" "$out/qnx"
  (cd "$run/$lib" && find . -type f -not -path '*/build/*' -not -name '*.o' -print) |
    while read -r f; do mkdir -p "$out/port/$(dirname "$f")"; cp "$run/$lib/$f" "$out/port/$f"; done
  cp "$run/report.html" "$out/"
  cp "$t/qnxtests.out" "$out/qnx/"
  if [ "$(du -sk "$t/target-logs" | cut -f1)" -gt 1024 ]; then
    # big suites: keep the logs of failing tests only; qnxtests.out lists every test
    mkdir -p "$out/qnx/logs"
    awk '$1 == "QNXTEST" && $3 != "PASS" {print $2}' "$t/qnxtests.out" | while read -r n; do
      cp "$t/target-logs/$n.out" "$out/qnx/logs/" 2>/dev/null || true; done
  else
    cp -r "$t/target-logs" "$out/qnx/logs"
  fi
  # no ":" in file names (test names like yaml-cpp::test): Windows can't check them out
  find "$out/qnx" -type f -name '*:*' | while read -r f; do
    n=$(basename "$f" | tr : _); mv "$f" "$(dirname "$f")/$n"
    sed -i "s#logs/$(basename "$f")#logs/$n#" "$out/qnx/qnxtests.out"; done
  if find "$out" -type f -print0 | xargs -0 file | grep -E ": *(ELF|ar archive)"
  then echo "error: ELF or archive file in $out (no QNX binaries in the repo)" >&2; exit 1; fi
  find "$out" -type f -print0 | xargs -0 sed -i "s/$home_re/~/g"
  echo "$lib: $(du -sh "$out" | cut -f1)"
done

if [ -n "$ip" ]; then
  ssh -o BatchMode=yes -i "$key" -o UserKnownHostsFile="$kh" "root@$ip" \
    'echo "$ uname -a"; uname -a; echo; echo "$ pidin info"; pidin info' > "$ev/qnx-target.txt"
fi
portpilot results "$runs" > "$ev/results.md"
clean "$ev/results.md"
