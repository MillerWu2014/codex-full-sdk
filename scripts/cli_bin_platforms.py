#!/usr/bin/env python3
"""Official public Codex package platforms → openai-codex-cli-bin wheel tags.

GitHub rust-v* ships exactly six `codex-package-*.tar.gz` archives (plus .zst
duplicates). openai-codex-cli-bin wheels in this repo match that set.

Linux public archives are musl, so those wheels are musllinux — the same tags
official uses when they rebuild musl packages into wheels. macOS/Windows tags
match the rust-v `openai_codex_cli_bin-*-py3-none-*.whl` filenames.

Official PyPI also publishes two extra manylinux wheels (gnu), which are on
the rust-v release as prebuilt wheels but have no public `*-linux-gnu`
package tarball. This table does not invent those.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CliBinPlatform:
    rust_target: str
    pep425_tag: str


# Order matches GitHub asset listing: apple, linux-musl, windows.
PLATFORMS: tuple[CliBinPlatform, ...] = (
    CliBinPlatform("aarch64-apple-darwin", "macosx_11_0_arm64"),
    CliBinPlatform("x86_64-apple-darwin", "macosx_10_9_x86_64"),
    CliBinPlatform("aarch64-unknown-linux-musl", "musllinux_1_1_aarch64"),
    CliBinPlatform("x86_64-unknown-linux-musl", "musllinux_1_1_x86_64"),
    CliBinPlatform("aarch64-pc-windows-msvc", "win_arm64"),
    CliBinPlatform("x86_64-pc-windows-msvc", "win_amd64"),
)

BY_TARGET: dict[str, CliBinPlatform] = {p.rust_target: p for p in PLATFORMS}


def rust_targets() -> tuple[str, ...]:
    return tuple(p.rust_target for p in PLATFORMS)


def pep425_tag(rust_target: str) -> str:
    platform = BY_TARGET.get(rust_target)
    if platform is None:
        raise RuntimeError(
            f"Unsupported rust target {rust_target!r}. "
            f"openai-codex-cli-bin ships these six: {', '.join(rust_targets())}"
        )
    return platform.pep425_tag


def runtime_binary_name(rust_target: str) -> str:
    return "codex.exe" if "windows" in rust_target else "codex"


def package_archive_name(rust_target: str) -> str:
    return f"codex-package-{rust_target}.tar.gz"


def github_package_url(release_tag: str, rust_target: str) -> str:
    return (
        "https://github.com/openai/codex/releases/download/"
        f"{release_tag}/{package_archive_name(rust_target)}"
    )


def check_release_wheels(wheels_dir: Path, version: str) -> None:
    cli_expected = {
        f"openai_codex_cli_bin-{version}-py3-none-{p.pep425_tag}.whl" for p in PLATFORMS
    }
    cli_actual = {path.name for path in wheels_dir.glob("openai_codex_cli_bin-*.whl")}
    sdk_expected = {f"openai_codex-{version}-py3-none-any.whl"}
    sdk_actual = {
        path.name
        for path in wheels_dir.glob("openai_codex-*.whl")
        if "cli_bin" not in path.name
    }
    if cli_actual != cli_expected:
        raise SystemExit(f"cli-bin wheels {sorted(cli_actual)} != {sorted(cli_expected)}")
    if sdk_actual != sdk_expected:
        raise SystemExit(f"SDK wheels {sorted(sdk_actual)} != {sorted(sdk_expected)}")


def _read_sdk_version(repo: Path) -> str:
    text = (repo / "sdk-v1" / "python" / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    if match is None:
        raise SystemExit("Could not read version from sdk-v1/python/pyproject.toml")
    return match.group(1)


def _self_check() -> None:
    assert len(PLATFORMS) == 6
    assert len({p.rust_target for p in PLATFORMS}) == 6
    assert len({p.pep425_tag for p in PLATFORMS}) == 6
    assert pep425_tag("aarch64-apple-darwin") == "macosx_11_0_arm64"
    assert runtime_binary_name("x86_64-pc-windows-msvc") == "codex.exe"
    assert runtime_binary_name("x86_64-unknown-linux-musl") == "codex"
    url = github_package_url("rust-v0.152.0", "aarch64-apple-darwin")
    assert url.endswith("codex-package-aarch64-apple-darwin.tar.gz")


if __name__ == "__main__":
    _self_check()
    if len(sys.argv) >= 2 and sys.argv[1] == "--check-wheels":
        repo = Path(__file__).resolve().parents[1]
        wheels = Path(sys.argv[2] if len(sys.argv) > 2 else repo / "dist" / "wheels")
        check_release_wheels(wheels, _read_sdk_version(repo))
        print(f"release wheels ok in {wheels}")
        raise SystemExit(0)
    print("cli_bin_platforms: 6 targets ok")
    for platform in PLATFORMS:
        print(f"  {platform.rust_target}  {platform.pep425_tag}")
