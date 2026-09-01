# Codex CLI Runtime for SDK v1

Platform-specific runtime package consumed by `sdk-v1/python` (`openai-codex`).

This package is staged during release so the SDK can pin an exact Codex CLI
version without checking platform binaries into the repo.

`openai-codex-cli-bin` is intentionally wheel-only. Do not build or publish an
sdist for this package.

Release ships **six** platform wheels, matching GitHub `codex-package-*.tar.gz`
on `rust-v*`: macOS arm64/x86_64, Linux musl arm64/x86_64, Windows arm64/x86_64.
Pack them with `python3 scripts/build_all.py --from-github-release --all-platforms`.
