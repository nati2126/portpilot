# PortPilot

Port Linux C/C++ libraries to QNX 8.0.

> Status: early. `portpilot scan` works. Patching, the build loop and on-target testing
> come next.

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

Linux or WSL, Python 3.11+, QNX SDP 8.0 installed.

```sh
python3 -m venv ~/venvs/portpilot
~/venvs/portpilot/bin/pip install -e .
source ~/qnx800/qnxsdp-env.sh

portpilot sdp-index                    # once: index your SDP (stays on your machine)
portpilot scan path/to/lib -o out/     # writes out/matrix.md and out/matrix.json
```

Useful options:
- `-D VAR=VALUE`: a CMake value the port passes, e.g. `-DCMAKE_REQUIRED_LIBRARIES=socket`.
- `--no-sdp`: scan without an SDP (less exact).
- `portpilot detect PATH`: print the build system.

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
