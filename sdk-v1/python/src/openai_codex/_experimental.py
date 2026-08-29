from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import ExperimentalApiDisabledError

if TYPE_CHECKING:
    from .client import CodexConfig


def require_experimental_api(config: CodexConfig, feature: str) -> None:
    """Reject experimental methods and fields unless the caller opted in."""
    if not config.experimental_api:
        raise ExperimentalApiDisabledError(f"{feature} requires CodexConfig.experimental_api=True")
