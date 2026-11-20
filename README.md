# PortPilot

[![CI](https://github.com/nati2126/portpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/nati2126/portpilot/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Port Linux C/C++ libraries to QNX 8.0.

> Status: works end to end on real libraries: scan, generate the port, build with qcc,
> fix, test on a QNX 8.0 target, report.

```sh
portpilot port https://github.com/<owner>/<lib> -o out/ --vm ~/qnx-work/vm-x86_64 [--ai]
```

That one command:

1. **Scans** the source and predicts how CMake will configure it on QNX.
2. **Applies known fixes** before building (each one cites a rule).
3. **Generates the port** in the [qnx-ports/build-files](https://github.com/qnx-ports/build-files)
   layout: `Makefile`, `common.mk`, toolchain, `qnxtests.sh`, `patches/qnx.patch`, `README.md`.
4. **Builds** it with your SDP. Errors are parsed. Ones a rule explains are fixed and rebuilt.
   A missing dependency is built from its official QNX port.
5. **Optional, `--ai`:** errors no rule covers go to a local model (Ollama). An edit is kept
   only if the rebuild shows the error gone and no new error in that file. Nothing leaves
   your machine.
6. **Runs the library's own tests** on the QNX target, fixes what a rule explains, and retests.
7. **Writes `out/report.html`:** every change with its reason and source, rejected AI
   edits, build attempts, test results, and the patch.

## What `portpilot scan` tells you

Point it at a CMake project. You get a dependency matrix in the format of the
[QNX porting guide](https://www.qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.qpg/topic/porting_Dependency_mapping.html):

- **What needs porting:** Linux-only APIs that QNX will compile, each with its QNX
  equivalent, a strategy, and a source.
- **Silent feature loss:** CMake checks that will fail on QNX and quietly switch features
  off, for example `recvmsg` living in `libsocket`.
- **What to ignore:** code QNX never compiles (Windows paths, an epoll backend that the build
  doesn't select on QNX), so it isn't reported as work.

To work this out, PortPilot predicts the CMake configure step for QNX from your own SDP:
which checks pass, which `if()` branches run, and which `#if` blocks are compiled. On nng
the prediction matches the real QNX `CMakeCache.txt` for 42 of 44 checks, with 0 wrong.

## Quick start

New to QNX ports? The [codelab](docs/codelab.md) walks through porting sockpp and running its tests on QNX 8.0 in about 30 minutes.

Linux or WSL, Python 3.11+, QNX SDP 8.0 installed.

```sh
python3 -m venv ~/venvs/portpilot
~/venvs/portpilot/bin/pip install -e .
source ~/qnx800/qnxsdp-env.sh

portpilot doctor                       # what's ready, what's missing, and how to fix it
portpilot sdp-index                    # once: index your SDP (stays on your machine)
portpilot port <github url> -o out/    # scan + port + build; add --vm DIR or --ip IP to test
portpilot test out/ --ip <target-ip>   # (re)run the tests on a QNX target
```

Other commands:
- `portpilot scan PATH -o out/`: only the dependency matrix (`matrix.md`, `matrix.json`).
  `-D VAR=VALUE` sets a CMake value the port passes.
- `portpilot report out/`: regenerate `report.html`.
- `portpilot atlas scan candidates.json -o atlas/`: scan many libraries (from
  `atlas/candidates.py`) and rank what blocks them on QNX. `portpilot atlas report atlas/`
  prints the summary.
- `portpilot diagnose build.log`: parse a QNX build log and list the rule fixes.
- `portpilot qnxtests BUILD_DIR`: write a target test runner from a CMake build tree.
- `portpilot pr out/ --author 'Name <email>'`: turn a tested port into a
  [build-files](https://github.com/qnx-ports/build-files) contribution, the way that repo's
  own port PRs look: `ports/<name>/`, `.github/workflows/<name>.yml` and a README row,
  committed on a branch of a local clone, plus `PR.md` with the QNX test results. It never
  pushes.
- `portpilot results DIR...`: one table over many port runs, from their `run.json`.
- `--no-sdp`: work without an SDP index (less exact).

Tests that need a service: `--service DIR='CMD'` copies DIR to the target and runs CMD
there during the tests (e.g. mosquitto, built from its official QNX port).
`--localhost host` points tests that connect to `localhost` at this machine instead
(paho.mqtt.c's tests against paho's test broker and proxy on the host, as in paho's CI).

## Results on QNX 8.0

12 C/C++ libraries, each ported from its latest GitHub release by `portpilot port <url>` with rules only (no AI), on QNX SDP 8.0, x86_64 QEMU target. Ten of them have no QNX port anywhere (checked against qnx-ports and repo.oss.qnx.com); zlib-ng and hiredis are packaged by QNX.

12/12 libraries built for QNX 8.0 from their upstream release; 7 tested on a QNX 8.0 QEMU target.

| Library | Release | Built | Build attempts | Fixes (AI) | Patch lines | Tests on QNX | Time |
|---|---|---|---|---|---|---|---|
| civetweb | `v1.16` | yes | 4 | 4 (0) | 2 | not run | 2.2 min |
| efsw | `1.7.3` | yes | 1 | 0 (0) | 0 | no tests built | 0.4 min |
| hiredis | `v1.5.0` | yes | 1 | 0 (0) | 0 | no tests built | 0.2 min |
| libcbor | `v0.14.0` | yes | 2 | 2 (0) | 0 | not run | 0.8 min |
| libcoap | `v4.3.5` | yes | 2 | 3 (0) | 0 | 176/176 cases (1/1 programs) | 4.3 min |
| libhv | `v1.3.4` | yes | 3 | 10 (0) | 14 | no tests built | 3.9 min |
| open62541 | `v1.5.10` | yes | 7 | 15 (0) | 25 | 5029/5187 cases (128/146 programs) | 10.2 min |
| paho.mqtt.c | `v1.3.16` | yes | 2 | 3 (0) | 8 | 95/103 programs | 0.7 min |
| sockpp | `v1.0.0` | yes | 4 | 7 (0) | 8 | 33/33 cases (1/1 programs) | 1.3 min |
| spdlog | `v1.17.0` | yes | 3 | 3 (0) | 3 | 180/180 cases (1/1 programs) | 1.8 min |
| yaml-cpp | `yaml-cpp-0.9.0` | yes | 1 | 1 (0) | 0 | 1008/1008 cases (1/1 programs) | 4.1 min |
| zlib-ng | `2.3.3` | yes | 1 | 0 (0) | 0 | 2/2 programs | 0.5 min |

Fixes count every change PortPilot applied (rules, dependency ports, AI); patch lines are the source lines in `patches/qnx.patch`. Generated by `portpilot results` from each run's `run.json`.

The outputs behind these numbers, including the QNX test logs and known failures, are in [`evidence/`](evidence/).

### What the local AI adds

`portpilot ai-eval` measures it on the compile errors of the libraries above and the benchmark libraries, starting from each port without the compiler flags its rules added. One error per file, 32 in all. A fix counts only if recompiling the file shows the error gone and no new error, including in headers the file includes. Model: `qwen2.5-coder:7b` on Ollama, offline.

| Condition | Errors fixed |
|---|---|
| Rules only | 17/32 |
| AI, no QNX facts | 0/32 |
| AI, with QNX facts (knowledge base + SDP index) | 6/32 |

- The QNX facts are what make the model useful. Without them it fixes nothing. With them it fixes 6 of the 17 errors a rule also fixes, without seeing the rules: 5 per-file `#define _QNX_SOURCE` and 1 `#include <strings.h>`. All 6 were reviewed by hand and are correct.
- None of the 15 errors no rule fixes is a small source fix: 11 are a missing test framework (CUnit, a dependency port), 2 need a redesign (kqueue, `prctl`) and 2 are a bloaty include-path problem. The model declines all 15 and makes no false fix.
- The eval found a false fix the port loop had accepted: the model moved workflow's `<sys/event.h>` error into an SDP driver-kit header ([F-018](docs/ground-truth.md#f-018)). Both checks now reject that.

Cases, model answers and edits: [`evidence/ai-eval/`](evidence/ai-eval/).

## Tested with

- QNX SDP 8.0 (GA 8.0.x packages), `qcc`/`q++` (gcc 12.2.0), target `x86_64`.
- Target: QNX 8.0 on QEMU/KVM, image built with the SDP's `mkqnximage --type=qemu`.
- Host: Ubuntu 24.04 on WSL 2. Ports build on a Linux host, as the official ports do.

## QNX-specific code, for reviewers

| What | Where |
|---|---|
| Rules: Linux feature → QNX fact → fix, each with its source | `src/portpilot/data/kb.toml` |
| Reads **your** SDP: headers, exported symbols, `qcc` macros | `sdp_index.py`: `build_index`, `predefined_macros` |
| Predicts CMake's configure on QNX (checks, `if()` branches) | `configure.py`, `scan_cmake.py` |
| Generates the build-files port: `common.mk`, `nto-<arch>/Makefile`, `qnx.nto.toolchain.cmake` | `scaffold.py`: `render_common_mk`, `render` |
| Builds with `qcc` through the port's `make install`, sources `qnxsdp-env.sh` | `build.py`: `sdp_env`, `run_make` |
| Parses `qcc`/`ld` errors and maps them to rules | `diagnostics.py`, `fixes.py`: `from_diagnostics` |
| Official QNX ports as dependencies (muslflt, Catch2, check, ...) | `deps.py`: `ensure_port`, `ensure_muslflt` |
| Test runner for the QNX target's `/bin/sh` | `qnxtests.py`: `render` |
| Boots the `mkqnximage` VM, copies tests, runs them over ssh | `target.py`: `vm_start`, `run_tests`, `start_service` |
| QNX behavior seen in test failures (float output, `sin_len`) | `testfail.py`, `fixes.py`: `bsd_sockaddr_len_fixes` |
| A build-files contribution (port, workflow, README row) | `pr.py`: `contribute` |
| Real output from QNX 8.0 | [`evidence/`](evidence/) |

## Where the QNX facts come from

- `src/portpilot/data/kb.toml`: the rules. Every rule cites the QNX docs or a measured fact.
- [`docs/ground-truth.md`](docs/ground-truth.md): what we measured on QNX 8.0 while porting
  fmt and nng by hand. The [`probes/`](probes/) folder has the programs.
- `portpilot sdp-index`: reads symbols, headers and compiler macros from **your** SDP. No
  SDP files are shipped in this repo.

## Development

```sh
pip install -e '.[dev]'
pytest && ruff check src tests && mypy
```

CI runs everything that doesn't need the SDP. `tests/test_ground_truth_nng.py` needs the
SDP and nng sources, so it runs locally (see the file for the variables to set).

## License

Apache-2.0
