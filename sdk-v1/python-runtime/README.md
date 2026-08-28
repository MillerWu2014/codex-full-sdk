# Codex CLI Runtime for SDK v1

Platform-specific runtime package consumed by `sdk-v1/python` (`openai-codex`).

This package is staged during release so the SDK can pin an exact Codex CLI
version without checking platform binaries into the repo.

`openai-codex-cli-bin` is intentionally wheel-only. Do not build or publish an
sdist for this package.
