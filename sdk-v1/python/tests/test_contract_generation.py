from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED_TARGETS = [
    Path("src/openai_codex/generated/notification_registry.py"),
    Path("src/openai_codex/generated/v2_all.py"),
    Path("src/openai_codex/api.py"),
]


def _snapshot_target(root: Path, rel_path: Path) -> dict[str, bytes] | bytes | None:
    """Capture one generated artifact so regeneration drift is easy to compare."""
    target = root / rel_path
    if not target.exists():
        return None
    if target.is_file():
        return target.read_bytes()

    snapshot: dict[str, bytes] = {}
    for path in sorted(target.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            snapshot[str(path.relative_to(target))] = path.read_bytes()
    return snapshot


def _snapshot_targets(root: Path) -> dict[str, dict[str, bytes] | bytes | None]:
    """Capture all checked-in generated artifacts before and after regeneration."""
    return {str(rel_path): _snapshot_target(root, rel_path) for rel_path in GENERATED_TARGETS}


def test_generated_files_are_up_to_date():
    """Regenerating from fallback schema sources should leave artifacts unchanged."""
    before = _snapshot_targets(ROOT)

    # Regenerate contract artifacts via the pinned runtime package, not a local
    # app-server binary from the checkout or CI environment.
    env = os.environ.copy()
    env.pop("CODEX_EXEC_PATH", None)
    python_bin = str(Path(sys.executable).parent)
    env["PATH"] = f"{python_bin}{os.pathsep}{env.get('PATH', '')}"

    cmd = [sys.executable, "scripts/update_sdk_artifacts.py", "generate-types"]
    codex_bin = env.get("CODEX_BIN")
    if codex_bin:
        cmd.extend(["--codex-bin", codex_bin])
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)

    after = _snapshot_targets(ROOT)
    assert before == after, "Generated files drifted after regeneration"


def test_generated_v2_surface_contains_required_p1_protocol_shapes() -> None:
    from openai_codex.generated import v2_all

    required_types = [
        "ThreadSearchRequest",
        "ThreadSearchOccurrencesRequest",
        "ProjectListRequest",
        "ProjectCreateRequest",
        "ProjectReadRequest",
        "ProjectUpdateRequest",
        "ProjectMoveRequest",
        "ProjectDeleteRequest",
        "ThreadQueueListRequest",
        "ThreadQueueAddRequest",
        "ThreadQueueUpdateRequest",
        "ThreadQueueDeleteRequest",
        "ThreadQueueReorderRequest",
        "ThreadQueueStartRequest",
        "TurnSettingsUpdateRequest",
        "MemoryResetRequest",
        "ThreadSearchResult",
        "Project",
        "QueuedSubmission",
        "ThreadSettingsUpdatedNotification",
        "CollaborationMode",
        "FuzzyFileSearchSessionUpdatedNotification",
        "FuzzyFileSearchSessionCompletedNotification",
        "MemoryResetResponse",
    ]
    for type_name in required_types:
        assert hasattr(v2_all, type_name), type_name
