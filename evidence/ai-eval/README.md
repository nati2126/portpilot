# AI eval

`portpilot ai-eval`: rules vs. a local model with and without QNX facts, on real compile errors.

| File | Corpus |
|---|---|
| `from-scratch.md`, `.json` | Each port without the compiler flags its rules added, so the errors those flags fixed come back. 32 cases. |
| `after-port-settings.md`, `.json` | Each port as shipped. Only the errors left after its settings. 17 cases. |

## Method

- The pristine upstream source is built once with the port's settings (CMake edits from the port kept, C/C++ files as upstream wrote them). The VERBOSE log gives each file's `qcc` command.
- A case is the first error in a file. Each condition is checked by recompiling that file alone: the error must be gone and no new error may appear, including in headers.
- `rules`: the knowledge-base rules, source edits and the compiler flags they set. `bare`: the model with the error and the code. `grounded`: the same prompt plus the QNX facts the port loop gives it.
- Model `qwen2.5-coder:7b` on Ollama, temperature 0, seed 7, 2 tries per case. Nothing leaves the machine.
- In the `.json` files, each condition's result has the model's edits, its NO_FIX reason and the facts it was given.

## Reproduce

```bash
portpilot ai-eval <portpilot port output dirs...> -o ~/ai-eval-scratch --no-cflags
```

## Limits

- 6 libraries have compile errors; most cases come from workflow and libcoap.
- One model. The cases are the ones these libraries produce, not a sample of all porting errors.
