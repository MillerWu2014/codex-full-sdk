# Local adapter + installed SDK examples

These scripts use the **installed** `openai-codex` wheel (the conda `codex`
env you already set up), not the checkout under `sdk-v1/python/src`.

They talk to Codex through the optional [`adapter/`](../../adapter/README.md)
process. They write an isolated `CODEX_HOME` under `.codex-home/` so they do
**not** read or overwrite `~/.codex/config.toml` (that file is often owned by
the Codex desktop app).

## Prerequisites

1. Adapter is running (`python3 adapter/server.py`), `/health` returns `ok`.
2. Local model server is up (this machine: LM Studio on `:1234`).
3. Wheels installed into the interpreter you will use:

```bash
conda activate codex
pip install dist/wheels/openai_codex_cli_bin-*.whl dist/wheels/openai_codex-*.whl
```

Optional:

```bash
export CODEX_ADAPTER_URL=http://127.0.0.1:18080
export CODEX_LOCAL_MODEL=ornith-1.5-9b   # otherwise first non-embedding /v1/models id
```

## Run

From this directory, with the same Python that has the wheels:

```bash
cd examples/local_adapter
python 01_runtime_apis.py      # RPCs that do not need a model completion
python 02_thread_run.py        # one short turn via the adapter
python 03_thread_stream.py     # stream events for one turn
python 04_async_run.py         # AsyncCodex parity
python 05_thread_lifecycle.py  # Thread resume/fork/archive/goal/queue/section/search/...
python 06_turn_controls.py     # steer during stream + interrupt
python 07_fs_write_watch.py    # FS write/copy/remove + watch via SDK write
```

`01` and `07` do not need a model completion. `02`–`06` hit the local model.
