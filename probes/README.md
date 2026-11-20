# Probes

Small C programs that measure one QNX behaviour each. They back the facts in
[docs/ground-truth.md](../docs/ground-truth.md), which PortPilot's rules cite.

| Probe | Fact | Run |
|---|---|---|
| `pipe_pollhup.c` | F-005: pipes don't report POLLHUP when the writer closes | `run_probe.sh pipe_pollhup -lsocket` |
| `nng_errnos.c` | F-006, F-007, F-008: errno/EAI values QNX returns | `run_probe.sh nng_errnos -lsocket` |
| `urandom_cost.c` | F-009: cost of a 4-byte `/dev/urandom` read | `run_probe.sh urandom_cost` |
| `peercred.c` | F-010: socketpair sockets have no peer credentials | `run_probe.sh peercred -lsocket` |
| `pipe_nonblock.c` | control: `O_NONBLOCK` on pipes works (read gives EAGAIN) | `run_probe.sh pipe_nonblock -lsocket` |
| `condclock.c` | control: timed waits honour `CLOCK_MONOTONIC` and `CLOCK_REALTIME` | `run_probe.sh condclock` |
| `strtod_subnormal.c` | F-015: `strtod` misrounds the largest subnormal and `DBL_MAX`; muslflt is exact | `run_probe.sh strtod_subnormal` (then add `.../libmuslflt.a -lm`) |
| `link_flags.sh` | F-011: `-lpthread`, `-lrt`, `-ldl` fail; `-pthread` works | `./link_flags.sh` (host only) |

`run_probe.sh` needs the SDP environment and `QNX_IP` set to a running QNX 8.0 target.
