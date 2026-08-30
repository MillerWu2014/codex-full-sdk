#!/usr/bin/env python3
"""Build the Codex CLI package, python-runtime wheel, and Python SDK wheel.

This script lives in the wrapper repo. It only *invokes* tools under `codex/`;
it does not modify the submodule.

    python3 scripts/build_all.py

Outputs land in `dist/` (gitignored):
  dist/codex-package/                          unpacked CLI package
  dist/codex-package-<target>.tar.gz           archive for stage-runtime
  dist/runtime-stage/                          staged openai-codex-cli-bin tree
  dist/sdk-stage/                              staged openai-codex tree
  dist/wheels/*.whl                            installable wheels
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_sdk_version(root: Path) -> str:
    text = (root / "sdk-v1" / "python" / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not read version from sdk-v1/python/pyproject.toml")
    return match.group(1)


def host_rust_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        machine = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        machine = "aarch64"
    mapping = {
        ("darwin", "aarch64"): "aarch64-apple-darwin",
        ("darwin", "x86_64"): "x86_64-apple-darwin",
        ("linux", "aarch64"): "aarch64-unknown-linux-musl",
        ("linux", "x86_64"): "x86_64-unknown-linux-musl",
        ("windows", "aarch64"): "aarch64-pc-windows-msvc",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
    }
    target = mapping.get((system, machine))
    if target is None:
        raise RuntimeError(
            f"Unsupported host platform {platform.system()}/{platform.machine()}. "
            "Pass --target explicitly."
        )
    return target


def runtime_binary_name() -> str:
    return "codex.exe" if os.name == "nt" else "codex"


def _executable(path: Path) -> str | None:
    if path.is_file():
        return str(path.resolve())
    return None


def prepend_dir_to_path(env: dict[str, str], directory: Path) -> None:
    env["PATH"] = f"{directory}{os.pathsep}{env.get('PATH', '')}"


def prepend_local_rust(root: Path, env: dict[str, str]) -> None:
    """Use a workspace-local rustup/cargo install when cargo is not on PATH."""
    if shutil.which("cargo", path=env.get("PATH")):
        return
    cargo_bin = root / ".tools" / "cargo" / "bin"
    cargo = cargo_bin / ("cargo.exe" if os.name == "nt" else "cargo")
    if not cargo.is_file():
        return
    prepend_dir_to_path(env, cargo_bin)
    env.setdefault("CARGO_HOME", str(root / ".tools" / "cargo"))
    env.setdefault("RUSTUP_HOME", str(root / ".tools" / "rustup"))


def rust_hint(root: Path) -> str:
    toolchain = (root / "codex" / "codex-rs" / "rust-toolchain.toml").read_text()
    channel_match = re.search(r'^channel\s*=\s*"([^"]+)"', toolchain, flags=re.MULTILINE)
    channel = channel_match.group(1) if channel_match else "stable"
    return (
        "Rust 环境不可用：找不到可用的 cargo/rustc。\n"
        "\n"
        "安装:\n"
        "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh\n"
        f"  rustup toolchain install {channel}\n"
        "  进入 codex/codex-rs 后 rustup 会按 rust-toolchain.toml 自动选用该版本。\n"
        "\n"
        "指定已有工具链:\n"
        "  python3 scripts/build_all.py --cargo \"$HOME/.cargo/bin/cargo\"\n"
        "  或把 cargo 放到仓库 .tools/cargo/bin/（脚本会自动发现）\n"
        "  也可设置 PATH / CARGO_HOME / RUSTUP_HOME"
    )


def sdk_python_hint() -> str:
    return (
        "sdk-v1 Python 环境不可用：需要 uv，以及 sdk-v1/python 的开发依赖"
        "（含 datamodel-code-generator）。\n"
        "\n"
        "安装:\n"
        "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "  cd sdk-v1/python && uv sync\n"
        "\n"
        "指定已有 uv:\n"
        "  python3 scripts/build_all.py --uv \"$HOME/.local/bin/uv\""
    )


def resolve_tool(name: str, explicit: str | None, env: dict[str, str], hint: str) -> str:
    if explicit:
        path = Path(explicit).expanduser()
        resolved = _executable(path)
        if resolved is None:
            raise RuntimeError(f"指定的 {name} 不存在: {path}\n\n{hint}")
        prepend_dir_to_path(env, path.parent)
        return resolved
    found = shutil.which(name, path=env.get("PATH"))
    if found is None:
        raise RuntimeError(hint)
    return found


def check_rust(cargo: str, env: dict[str, str], root: Path) -> None:
    rustc = shutil.which("rustc", path=env.get("PATH"))
    if rustc is None:
        raise RuntimeError(rust_hint(root))
    try:
        cargo_v = subprocess.check_output(
            [cargo, "--version"], env=env, text=True, stderr=subprocess.STDOUT
        ).strip()
        rustc_v = subprocess.check_output(
            [rustc, "--version"], env=env, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"{rust_hint(root)}\n\n探测失败: {exc}") from exc
    print(f"Rust OK: {cargo_v}  ({cargo})", flush=True)
    print(f"         {rustc_v}  ({rustc})", flush=True)


def check_sdk_python(uv: str, sdk_python: Path, env: dict[str, str]) -> None:
    if not (sdk_python / "pyproject.toml").is_file():
        raise RuntimeError(f"缺少 sdk-v1/python/pyproject.toml: {sdk_python}")
    try:
        uv_v = subprocess.check_output(
            [uv, "--version"], env=env, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"{sdk_python_hint()}\n\n探测失败: {exc}") from exc
    probe = [
        uv,
        "run",
        "--project",
        str(sdk_python),
        "--no-sync",
        "python",
        "-c",
        "import datamodel_code_generator; import sys; print(sys.executable)",
    ]
    proc = subprocess.run(
        probe, cwd=sdk_python, env=env, text=True, capture_output=True
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        extra = f"\n\n探测失败:\n{detail}" if detail else ""
        raise RuntimeError(f"{sdk_python_hint()}{extra}")
    print(f"SDK Python OK: {uv_v}  ({uv})", flush=True)
    print(f"               {proc.stdout.strip()}", flush=True)


def sdk_python_cmd(uv: str, script: Path, *args: str) -> list[str]:
    """Invoke an sdk-v1/python script inside that project's uv environment.

    stage-sdk runs datamodel-code-generator via ``sys.executable -m``. That
    package is a uv *dev* dependency, not something the wrapper's python has.
    Official release does the same: ``uv run python scripts/update_sdk_artifacts.py``.
    """
    return [uv, "run", "python", str(script), *args]


def run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def rm_and_mkdir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def build_wheel(uv: str, stage_dir: Path, wheels_dir: Path, env: dict[str, str]) -> list[Path]:
    """Build into a fresh dir, then copy. Same-name overwrite in dist/wheels is expected."""
    wheels_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-wheel-") as tmp:
        tmp_dir = Path(tmp)
        run([uv, "build", "--wheel", "--out-dir", str(tmp_dir)], cwd=stage_dir, env=env)
        built = sorted(tmp_dir.glob("*.whl"))
        if not built:
            raise RuntimeError(f"uv build produced no wheels in {tmp_dir}")
        copied: list[Path] = []
        for wheel in built:
            dest = wheels_dir / wheel.name
            shutil.copy2(wheel, dest)
            copied.append(dest)
        return copied


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Codex CLI package, python-runtime wheel, and Python SDK wheel."
    )
    parser.add_argument(
        "--version",
        help="Version written into both wheels. Defaults to sdk-v1/python pyproject version.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Output directory. Defaults to <repo>/dist.",
    )
    parser.add_argument(
        "--target",
        help="Rust target triple. Defaults to this host's release target.",
    )
    parser.add_argument(
        "--cargo-profile",
        default="release",
        help="Cargo profile for CLI binaries (default: release).",
    )
    parser.add_argument(
        "--skip-cli",
        action="store_true",
        help="Reuse an existing dist/codex-package archive instead of rebuilding the CLI.",
    )
    parser.add_argument(
        "--cargo",
        help="Path to cargo. Defaults to PATH, then <repo>/.tools/cargo/bin/cargo.",
    )
    parser.add_argument(
        "--uv",
        help="Path to uv. Defaults to PATH.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    codex_root = root / "codex"
    if not (codex_root / "scripts" / "build_codex_package.py").is_file():
        raise RuntimeError(
            f"Codex submodule is missing at {codex_root}. "
            "Run: git submodule update --init --recursive"
        )

    version = args.version or read_sdk_version(root)
    out_dir = (args.out_dir or (root / "dist")).resolve()
    target = args.target or host_rust_target()
    package_dir = out_dir / "codex-package"
    archive_path = out_dir / f"codex-package-{target}.tar.gz"
    runtime_stage = out_dir / "runtime-stage"
    sdk_stage = out_dir / "sdk-stage"
    wheels_dir = out_dir / "wheels"
    update_script = root / "sdk-v1" / "python" / "scripts" / "update_sdk_artifacts.py"
    env = os.environ.copy()
    env["CODEX_REPO_ROOT"] = str(codex_root)
    sdk_python = root / "sdk-v1" / "python"
    python = sys.executable

    uv = resolve_tool("uv", args.uv, env, sdk_python_hint())
    check_sdk_python(uv, sdk_python, env)

    cargo: str | None = None
    if not args.skip_cli:
        if not args.cargo:
            prepend_local_rust(root, env)
        cargo = resolve_tool("cargo", args.cargo, env, rust_hint(root))
        check_rust(cargo, env, root)

    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_cli:
        if not archive_path.is_file():
            raise RuntimeError(f"--skip-cli requires existing archive: {archive_path}")
        print(f"Reusing CLI archive {archive_path}")
    else:
        assert cargo is not None
        run(
            [
                python,
                str(codex_root / "scripts" / "build_codex_package.py"),
                "--target",
                target,
                "--package-version",
                version,
                "--package-dir",
                str(package_dir),
                "--archive-output",
                str(archive_path),
                "--cargo-profile",
                args.cargo_profile,
                "--cargo",
                cargo,
                "--force",
            ],
            cwd=codex_root,
            env=env,
        )

    rm_and_mkdir(runtime_stage)
    run(
        sdk_python_cmd(
            uv,
            update_script,
            "stage-runtime",
            str(runtime_stage),
            str(archive_path),
            "--codex-version",
            version,
        ),
        cwd=sdk_python,
        env=env,
    )
    runtime_wheels = build_wheel(uv, runtime_stage, wheels_dir, env)

    codex_bin = package_dir / "bin" / runtime_binary_name()
    if not codex_bin.is_file():
        # --skip-cli may not have unpacked package_dir; extract the archive once.
        package_dir.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(archive_path, package_dir)
        codex_bin = package_dir / "bin" / runtime_binary_name()
    if not codex_bin.is_file():
        raise RuntimeError(f"Codex binary missing after CLI package build: {codex_bin}")

    rm_and_mkdir(sdk_stage)
    run(
        sdk_python_cmd(
            uv,
            update_script,
            "stage-sdk",
            str(sdk_stage),
            "--sdk-version",
            version,
            "--codex-bin",
            str(codex_bin),
        ),
        cwd=sdk_python,
        env=env,
    )
    sdk_wheels = build_wheel(uv, sdk_stage, wheels_dir, env)

    print("\nBuilt wheels:")
    for wheel in [*runtime_wheels, *sdk_wheels]:
        print(f"  {wheel}")
    print("\nInstall with:")
    print("  pip install " + " ".join(str(w) for w in [*runtime_wheels, *sdk_wheels]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
