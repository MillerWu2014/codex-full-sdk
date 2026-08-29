from __future__ import annotations

import pytest

from openai_codex import CodexConfig, ExperimentalApiDisabledError
from openai_codex._experimental import require_experimental_api


def test_require_experimental_api_passes_when_enabled() -> None:
    require_experimental_api(CodexConfig(experimental_api=True), "project/list")


def test_require_experimental_api_raises_when_disabled() -> None:
    with pytest.raises(ExperimentalApiDisabledError, match="project/list"):
        require_experimental_api(CodexConfig(experimental_api=False), "project/list")
