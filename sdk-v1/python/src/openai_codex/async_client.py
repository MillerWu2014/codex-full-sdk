from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from typing import AsyncIterator, Callable, ParamSpec, TypeVar

from pydantic import BaseModel

from ._goal import _GoalOperationState
from .client import CodexClient, CodexConfig
from .generated import v2_all as v2
from .generated.v2_all import (
    AccountLoginCompletedNotification,
    AgentMessageDeltaNotification,
    CancelLoginAccountResponse,
    GetAccountParams as V2GetAccountParams,
    GetAccountResponse,
    LoginAccountParams as V2LoginAccountParams,
    LoginAccountResponse,
    LogoutAccountResponse,
    ModelListResponse,
    ThreadArchiveResponse,
    ThreadCompactStartResponse,
    ThreadForkParams as V2ThreadForkParams,
    ThreadForkResponse,
    ThreadGoalClearResponse,
    ThreadGoalSetResponse,
    ThreadGoalStatus,
    ThreadListParams as V2ThreadListParams,
    ThreadListResponse,
    ThreadReadResponse,
    ThreadResumeParams as V2ThreadResumeParams,
    ThreadResumeResponse,
    ThreadSetNameResponse,
    ThreadStartParams as V2ThreadStartParams,
    ThreadStartResponse,
    ThreadUnarchiveResponse,
    TurnCompletedNotification,
    TurnInterruptResponse,
    TurnStartParams as V2TurnStartParams,
    TurnStartResponse,
    TurnSteerResponse,
)
from .models import InitializeResponse, JsonObject, Notification
from .types import (
    FuzzyFileSearchResponse,
    FuzzyFileSearchSessionStartResponse,
    FuzzyFileSearchSessionStopResponse,
    FuzzyFileSearchSessionUpdateResponse,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
ParamsT = ParamSpec("ParamsT")
ReturnT = TypeVar("ReturnT")


class AsyncCodexClient:
    """Async wrapper around CodexClient using thread offloading."""

    def __init__(self, config: CodexConfig | None = None) -> None:
        """Create the wrapped sync client that owns the transport process."""
        self._sync = CodexClient(config=config)

    @property
    def config(self) -> CodexConfig:
        """Return the wrapped sync client's process configuration."""
        return self._sync.config

    async def __aenter__(self) -> "AsyncCodexClient":
        """Start the Codex process when entering an async context."""
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        """Close the Codex process when leaving an async context."""
        await self.close()

    async def _call_sync(
        self,
        fn: Callable[ParamsT, ReturnT],
        /,
        *args: ParamsT.args,
        **kwargs: ParamsT.kwargs,
    ) -> ReturnT:
        """Run a blocking sync-client operation without blocking the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _next_from_iterator(
        iterator: Iterator[AgentMessageDeltaNotification],
    ) -> tuple[bool, AgentMessageDeltaNotification | None]:
        """Convert StopIteration into a value that can cross asyncio.to_thread."""
        try:
            return True, next(iterator)
        except StopIteration:
            return False, None

    async def start(self) -> None:
        """Start the wrapped sync client in a worker thread."""
        await self._call_sync(self._sync.start)

    async def close(self) -> None:
        """Close the wrapped sync client in a worker thread."""
        await self._call_sync(self._sync.close)

    async def initialize(self) -> InitializeResponse:
        """Initialize the Codex session."""
        return await self._call_sync(self._sync.initialize)

    def register_turn_notifications(self, turn_id: str) -> None:
        """Register a turn notification queue on the wrapped sync client."""
        self._sync.register_turn_notifications(turn_id)

    def register_login_notifications(self, login_id: str) -> None:
        """Register a login notification queue on the wrapped sync client."""
        self._sync.register_login_notifications(login_id)

    def unregister_login_notifications(self, login_id: str) -> None:
        """Unregister a login notification queue on the wrapped sync client."""
        self._sync.unregister_login_notifications(login_id)

    def unregister_turn_notifications(self, turn_id: str) -> None:
        """Unregister a turn notification queue on the wrapped sync client."""
        self._sync.unregister_turn_notifications(turn_id)

    def register_watch_notifications(self, watch_id: str) -> None:
        """Register an fs/watch notification queue on the wrapped sync client."""
        self._sync.register_watch_notifications(watch_id)

    def unregister_watch_notifications(self, watch_id: str) -> None:
        """Unregister an fs/watch notification queue on the wrapped sync client."""
        self._sync.unregister_watch_notifications(watch_id)

    async def next_watch_notification(self, watch_id: str) -> Notification | None:
        """Wait for the next fs/changed notification without blocking the event loop."""
        return await self._call_sync(self._sync.next_watch_notification, watch_id)

    def register_goal_operation(self, thread_id: str) -> _GoalOperationState:
        """Register a logical goal route on the wrapped sync client."""
        return self._sync.register_goal_operation(thread_id)

    def unregister_goal_operation(self, state: _GoalOperationState) -> None:
        """Release one logical goal route."""
        self._sync.unregister_goal_operation(state)

    async def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: type[ModelT],
    ) -> ModelT:
        """Send a typed JSON-RPC request through the wrapped sync client."""
        return await self._call_sync(
            self._sync.request,
            method,
            params,
            response_model=response_model,
        )

    async def account_login_start(
        self,
        params: V2LoginAccountParams | JsonObject,
    ) -> LoginAccountResponse:
        """Start one account login attempt through the wrapped sync client."""
        return await self._call_sync(self._sync.account_login_start, params)

    async def account_login_cancel(self, login_id: str) -> CancelLoginAccountResponse:
        """Cancel one active account login attempt through the wrapped sync client."""
        return await self._call_sync(self._sync.account_login_cancel, login_id)

    async def account_read(
        self,
        params: V2GetAccountParams | JsonObject | None = None,
    ) -> GetAccountResponse:
        """Read current account state through the wrapped sync client."""
        return await self._call_sync(self._sync.account_read, params)

    async def account_logout(self) -> LogoutAccountResponse:
        """Clear the active account session through the wrapped sync client."""
        return await self._call_sync(self._sync.account_logout)

    async def thread_start(
        self, params: V2ThreadStartParams | JsonObject | None = None
    ) -> ThreadStartResponse:
        """Start a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_start, params)

    async def thread_resume(
        self,
        thread_id: str,
        params: V2ThreadResumeParams | JsonObject | None = None,
    ) -> ThreadResumeResponse:
        """Resume a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_resume, thread_id, params)

    async def thread_list(
        self, params: V2ThreadListParams | JsonObject | None = None
    ) -> ThreadListResponse:
        """List threads using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_list, params)

    async def thread_read(self, thread_id: str, include_turns: bool = False) -> ThreadReadResponse:
        """Read a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_read, thread_id, include_turns)

    async def thread_fork(
        self,
        thread_id: str,
        params: V2ThreadForkParams | JsonObject | None = None,
    ) -> ThreadForkResponse:
        """Fork a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_fork, thread_id, params)

    async def thread_archive(self, thread_id: str) -> ThreadArchiveResponse:
        """Archive a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_archive, thread_id)

    async def thread_unarchive(self, thread_id: str) -> ThreadUnarchiveResponse:
        """Unarchive a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_unarchive, thread_id)

    async def thread_set_name(self, thread_id: str, name: str) -> ThreadSetNameResponse:
        """Rename a thread using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_set_name, thread_id, name)

    async def thread_compact(self, thread_id: str) -> ThreadCompactStartResponse:
        """Start thread compaction using the wrapped sync client."""
        return await self._call_sync(self._sync.thread_compact, thread_id)

    async def thread_goal_clear(self, thread_id: str) -> ThreadGoalClearResponse:
        """Clear the persisted goal through the wrapped sync client."""
        return await self._call_sync(self._sync.thread_goal_clear, thread_id)

    async def thread_goal_set(
        self,
        thread_id: str,
        *,
        objective: str | None = None,
        status: ThreadGoalStatus | None = None,
    ) -> ThreadGoalSetResponse:
        """Create or update a persisted goal through the wrapped sync client."""
        return await self._call_sync(
            self._sync.thread_goal_set,
            thread_id,
            objective=objective,
            status=status,
        )

    async def pause_goal(self, thread_id: str) -> ThreadGoalSetResponse:
        """Pause the active goal through the wrapped sync client."""
        return await self._call_sync(self._sync.pause_goal, thread_id)

    async def cancel_goal_operation(self, state: _GoalOperationState) -> None:
        """Stop continuation work after a logical goal operation is cancelled."""
        await self._call_sync(self._sync.cancel_goal_operation, state)

    async def start_goal_operation(
        self,
        thread_id: str,
        objective: str,
    ) -> tuple[_GoalOperationState, str]:
        """Start a logical goal through the wrapped sync client."""
        operation: Future[tuple[_GoalOperationState, str]] = Future()

        def start_operation() -> None:
            try:
                operation.set_result(self._sync.start_goal_operation(thread_id, objective))
            except BaseException as exc:
                operation.set_exception(exc)

        worker = threading.Thread(
            target=start_operation,
            name="codex-goal-start",
            daemon=True,
        )
        worker.start()
        try:
            return await asyncio.shield(asyncio.wrap_future(operation))
        except asyncio.CancelledError:

            def cleanup_cancelled_start(
                completed: Future[tuple[_GoalOperationState, str]],
            ) -> None:
                try:
                    state, _ = completed.result()
                except BaseException:
                    return

                def stop_cancelled_goal() -> None:
                    try:
                        self._sync.cancel_goal_operation(state)
                    finally:
                        state.finish()
                        self._sync.unregister_goal_operation(state)

                threading.Thread(
                    target=stop_cancelled_goal,
                    name="codex-goal-start-cleanup",
                    daemon=True,
                ).start()

            operation.add_done_callback(cleanup_cancelled_start)
            raise

    async def turn_start(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> TurnStartResponse:
        """Start a turn using the wrapped sync client."""
        return await self._call_sync(self._sync.turn_start, thread_id, input_items, params)

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> TurnInterruptResponse:
        """Interrupt a turn using the wrapped sync client."""
        return await self._call_sync(self._sync.turn_interrupt, thread_id, turn_id)

    async def turn_steer(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> TurnSteerResponse:
        """Send steering input to a turn using the wrapped sync client."""
        return await self._call_sync(
            self._sync.turn_steer,
            thread_id,
            expected_turn_id,
            input_items,
        )

    async def model_list(self, include_hidden: bool = False) -> ModelListResponse:
        """List models using the wrapped sync client."""
        return await self._call_sync(self._sync.model_list, include_hidden)

    async def thread_delete(
        self, params: v2.ThreadDeleteParams | JsonObject
    ) -> v2.ThreadDeleteResponse:
        return await self._call_sync(self._sync.thread_delete, params)

    async def thread_unsubscribe(
        self, params: v2.ThreadUnsubscribeParams | JsonObject
    ) -> v2.ThreadUnsubscribeResponse:
        return await self._call_sync(self._sync.thread_unsubscribe, params)

    async def thread_loaded_list(
        self, params: v2.ThreadLoadedListParams | JsonObject | None = None
    ) -> v2.ThreadLoadedListResponse:
        return await self._call_sync(self._sync.thread_loaded_list, params)

    async def thread_turns_list(
        self, params: v2.ThreadTurnsListParams | JsonObject
    ) -> v2.ThreadTurnsListResponse:
        return await self._call_sync(self._sync.thread_turns_list, params)

    async def thread_items_list(
        self, params: v2.ThreadItemsListParams | JsonObject
    ) -> v2.ThreadItemsListResponse:
        return await self._call_sync(self._sync.thread_items_list, params)

    async def thread_revert(
        self, params: v2.ThreadRevertParams | JsonObject
    ) -> v2.ThreadRevertResponse:
        return await self._call_sync(self._sync.thread_revert, params)

    async def thread_inject_items(
        self, params: v2.ThreadInjectItemsParams | JsonObject
    ) -> v2.ThreadInjectItemsResponse:
        return await self._call_sync(self._sync.thread_inject_items, params)

    async def thread_metadata_update(
        self, params: v2.ThreadMetadataUpdateParams | JsonObject
    ) -> v2.ThreadMetadataUpdateResponse:
        return await self._call_sync(self._sync.thread_metadata_update, params)

    async def thread_section_move(
        self, params: v2.ThreadSectionMoveParams | JsonObject
    ) -> v2.ThreadSectionMoveResponse:
        return await self._call_sync(self._sync.thread_section_move, params)

    async def thread_goal_get(
        self, params: v2.ThreadGoalGetParams | JsonObject
    ) -> v2.ThreadGoalGetResponse:
        return await self._call_sync(self._sync.thread_goal_get, params)

    async def thread_section_list(
        self, params: v2.ThreadSectionListParams | JsonObject | None = None
    ) -> v2.ThreadSectionListResponse:
        return await self._call_sync(self._sync.thread_section_list, params)

    async def thread_section_create(
        self, params: v2.ThreadSectionCreateParams | JsonObject
    ) -> v2.ThreadSectionCreateResponse:
        return await self._call_sync(self._sync.thread_section_create, params)

    async def thread_section_update(
        self, params: v2.ThreadSectionUpdateParams | JsonObject
    ) -> v2.ThreadSectionUpdateResponse:
        return await self._call_sync(self._sync.thread_section_update, params)

    async def thread_section_delete(
        self, params: v2.ThreadSectionDeleteParams | JsonObject
    ) -> v2.ThreadSectionDeleteResponse:
        return await self._call_sync(self._sync.thread_section_delete, params)

    async def skills_list(
        self, params: v2.SkillsListParams | JsonObject | None = None
    ) -> v2.SkillsListResponse:
        return await self._call_sync(self._sync.skills_list, params)

    async def skills_extra_roots_set(
        self, params: v2.SkillsExtraRootsSetParams | JsonObject
    ) -> v2.SkillsExtraRootsSetResponse:
        return await self._call_sync(self._sync.skills_extra_roots_set, params)

    async def skills_config_write(
        self, params: v2.SkillsConfigWriteParams | JsonObject
    ) -> v2.SkillsConfigWriteResponse:
        return await self._call_sync(self._sync.skills_config_write, params)

    async def plugin_skill_read(
        self, params: v2.PluginSkillReadParams | JsonObject
    ) -> v2.PluginSkillReadResponse:
        return await self._call_sync(self._sync.plugin_skill_read, params)

    async def mcp_reload(self) -> v2.McpServerRefreshResponse:
        return await self._call_sync(self._sync.mcp_reload)

    async def mcp_status_list(
        self, params: v2.ListMcpServerStatusParams | JsonObject | None = None
    ) -> v2.ListMcpServerStatusResponse:
        return await self._call_sync(self._sync.mcp_status_list, params)

    async def mcp_resource_read(
        self, params: v2.McpResourceReadParams | JsonObject
    ) -> v2.McpResourceReadResponse:
        return await self._call_sync(self._sync.mcp_resource_read, params)

    async def mcp_tool_call(
        self, params: v2.McpServerToolCallParams | JsonObject
    ) -> v2.McpServerToolCallResponse:
        return await self._call_sync(self._sync.mcp_tool_call, params)

    async def config_read(
        self, params: v2.ConfigReadParams | JsonObject | None = None
    ) -> v2.ConfigReadResponse:
        return await self._call_sync(self._sync.config_read, params)

    async def config_value_write(
        self, params: v2.ConfigValueWriteParams | JsonObject
    ) -> v2.ConfigWriteResponse:
        return await self._call_sync(self._sync.config_value_write, params)

    async def config_batch_write(
        self, params: v2.ConfigBatchWriteParams | JsonObject
    ) -> v2.ConfigWriteResponse:
        return await self._call_sync(self._sync.config_batch_write, params)

    async def config_requirements_read(self) -> v2.ConfigRequirementsReadResponse:
        return await self._call_sync(self._sync.config_requirements_read)

    async def experimental_feature_list(
        self, params: v2.ExperimentalFeatureListParams | JsonObject | None = None
    ) -> v2.ExperimentalFeatureListResponse:
        return await self._call_sync(self._sync.experimental_feature_list, params)

    async def experimental_feature_enablement_set(
        self, params: v2.ExperimentalFeatureEnablementSetParams | JsonObject
    ) -> v2.ExperimentalFeatureEnablementSetResponse:
        return await self._call_sync(self._sync.experimental_feature_enablement_set, params)

    async def external_agent_config_detect(
        self, params: v2.ExternalAgentConfigDetectParams | JsonObject | None = None
    ) -> v2.ExternalAgentConfigDetectResponse:
        return await self._call_sync(self._sync.external_agent_config_detect, params)

    async def external_agent_config_import(
        self, params: v2.ExternalAgentConfigImportParams | JsonObject
    ) -> v2.ExternalAgentConfigImportResponse:
        return await self._call_sync(self._sync.external_agent_config_import, params)

    async def external_agent_config_import_read_histories(
        self,
    ) -> v2.ExternalAgentConfigImportHistoriesReadResponse:
        return await self._call_sync(self._sync.external_agent_config_import_read_histories)

    async def model_provider_capabilities(self) -> v2.ModelProviderCapabilitiesReadResponse:
        return await self._call_sync(self._sync.model_provider_capabilities)

    async def fs_read_file(self, params: v2.FsReadFileParams | JsonObject) -> v2.FsReadFileResponse:
        return await self._call_sync(self._sync.fs_read_file, params)

    async def fs_write_file(
        self, params: v2.FsWriteFileParams | JsonObject
    ) -> v2.FsWriteFileResponse:
        return await self._call_sync(self._sync.fs_write_file, params)

    async def fs_create_directory(
        self, params: v2.FsCreateDirectoryParams | JsonObject
    ) -> v2.FsCreateDirectoryResponse:
        return await self._call_sync(self._sync.fs_create_directory, params)

    async def fs_get_metadata(
        self, params: v2.FsGetMetadataParams | JsonObject
    ) -> v2.FsGetMetadataResponse:
        return await self._call_sync(self._sync.fs_get_metadata, params)

    async def fs_read_directory(
        self, params: v2.FsReadDirectoryParams | JsonObject
    ) -> v2.FsReadDirectoryResponse:
        return await self._call_sync(self._sync.fs_read_directory, params)

    async def fs_remove(self, params: v2.FsRemoveParams | JsonObject) -> v2.FsRemoveResponse:
        return await self._call_sync(self._sync.fs_remove, params)

    async def fs_copy(self, params: v2.FsCopyParams | JsonObject) -> v2.FsCopyResponse:
        return await self._call_sync(self._sync.fs_copy, params)

    async def fs_watch(self, params: v2.FsWatchParams | JsonObject) -> v2.FsWatchResponse:
        return await self._call_sync(self._sync.fs_watch, params)

    async def fs_unwatch(self, params: v2.FsUnwatchParams | JsonObject) -> v2.FsUnwatchResponse:
        return await self._call_sync(self._sync.fs_unwatch, params)

    async def fuzzy_file_search(
        self, params: v2.FuzzyFileSearchParams | JsonObject
    ) -> FuzzyFileSearchResponse:
        return await self._call_sync(self._sync.fuzzy_file_search, params)

    async def thread_search(
        self, params: v2.ThreadSearchParams | JsonObject
    ) -> v2.ThreadSearchResponse:
        return await self._call_sync(self._sync.thread_search, params)

    async def thread_search_occurrences(
        self, params: v2.ThreadSearchOccurrencesParams | JsonObject
    ) -> v2.ThreadSearchOccurrencesResponse:
        return await self._call_sync(self._sync.thread_search_occurrences, params)

    async def collaboration_mode_list(self) -> v2.CollaborationModeListResponse:
        return await self._call_sync(self._sync.collaboration_mode_list)

    async def fuzzy_file_search_session_start(
        self, params: v2.FuzzyFileSearchSessionStartParams | JsonObject
    ) -> FuzzyFileSearchSessionStartResponse:
        return await self._call_sync(self._sync.fuzzy_file_search_session_start, params)

    async def fuzzy_file_search_session_update(
        self, params: v2.FuzzyFileSearchSessionUpdateParams | JsonObject
    ) -> FuzzyFileSearchSessionUpdateResponse:
        return await self._call_sync(self._sync.fuzzy_file_search_session_update, params)

    async def fuzzy_file_search_session_stop(
        self, params: v2.FuzzyFileSearchSessionStopParams | JsonObject
    ) -> FuzzyFileSearchSessionStopResponse:
        return await self._call_sync(self._sync.fuzzy_file_search_session_stop, params)

    async def memory_reset(self) -> v2.MemoryResetResponse:
        return await self._call_sync(self._sync.memory_reset)

    async def thread_memory_mode_set(
        self, params: v2.ThreadMemoryModeSetParams | JsonObject
    ) -> v2.ThreadMemoryModeSetResponse:
        return await self._call_sync(self._sync.thread_memory_mode_set, params)

    async def thread_settings_update(
        self, params: v2.ThreadSettingsUpdateParams | JsonObject
    ) -> v2.ThreadSettingsUpdateResponse:
        return await self._call_sync(self._sync.thread_settings_update, params)

    async def turn_settings_update(
        self, params: v2.TurnSettingsUpdateParams | JsonObject
    ) -> v2.TurnSettingsUpdateResponse:
        return await self._call_sync(self._sync.turn_settings_update, params)

    async def thread_queue_add(
        self, params: v2.ThreadQueueAddParams | JsonObject
    ) -> v2.ThreadQueueAddResponse:
        return await self._call_sync(self._sync.thread_queue_add, params)

    async def thread_queue_list(
        self, params: v2.ThreadQueueListParams | JsonObject
    ) -> v2.ThreadQueueListResponse:
        return await self._call_sync(self._sync.thread_queue_list, params)

    async def thread_queue_update(
        self, params: v2.ThreadQueueUpdateParams | JsonObject
    ) -> v2.ThreadQueueUpdateResponse:
        return await self._call_sync(self._sync.thread_queue_update, params)

    async def thread_queue_delete(
        self, params: v2.ThreadQueueDeleteParams | JsonObject
    ) -> v2.ThreadQueueDeleteResponse:
        return await self._call_sync(self._sync.thread_queue_delete, params)

    async def thread_queue_reorder(
        self, params: v2.ThreadQueueReorderParams | JsonObject
    ) -> v2.ThreadQueueReorderResponse:
        return await self._call_sync(self._sync.thread_queue_reorder, params)

    async def thread_queue_start(
        self, params: v2.ThreadQueueStartParams | JsonObject
    ) -> v2.ThreadQueueStartResponse:
        return await self._call_sync(self._sync.thread_queue_start, params)

    async def project_list(
        self, params: v2.ProjectListParams | JsonObject | None = None
    ) -> v2.ProjectListResponse:
        return await self._call_sync(self._sync.project_list, params)

    async def project_read(
        self, params: v2.ProjectReadParams | JsonObject
    ) -> v2.ProjectReadResponse:
        return await self._call_sync(self._sync.project_read, params)

    async def project_create(
        self, params: v2.ProjectCreateParams | JsonObject
    ) -> v2.ProjectCreateResponse:
        return await self._call_sync(self._sync.project_create, params)

    async def project_import(
        self, params: v2.ProjectImportParams | JsonObject
    ) -> v2.ProjectImportResponse:
        return await self._call_sync(self._sync.project_import, params)

    async def project_update(
        self, params: v2.ProjectUpdateParams | JsonObject
    ) -> v2.ProjectUpdateResponse:
        return await self._call_sync(self._sync.project_update, params)

    async def project_move(
        self, params: v2.ProjectMoveParams | JsonObject
    ) -> v2.ProjectMoveResponse:
        return await self._call_sync(self._sync.project_move, params)

    async def project_delete(
        self, params: v2.ProjectDeleteParams | JsonObject
    ) -> v2.ProjectDeleteResponse:
        return await self._call_sync(self._sync.project_delete, params)

    async def request_with_retry_on_overload(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: type[ModelT],
        max_attempts: int = 3,
        initial_delay_s: float = 0.25,
        max_delay_s: float = 2.0,
    ) -> ModelT:
        """Send a typed request with the sync client's overload retry policy."""
        return await self._call_sync(
            self._sync.request_with_retry_on_overload,
            method,
            params,
            response_model=response_model,
            max_attempts=max_attempts,
            initial_delay_s=initial_delay_s,
            max_delay_s=max_delay_s,
        )

    async def next_notification(self) -> Notification:
        """Wait for the next global notification without blocking the event loop."""
        return await self._call_sync(self._sync.next_notification)

    async def next_login_notification(self, login_id: str) -> Notification:
        """Wait for the next notification routed to one login attempt."""
        return await self._call_sync(self._sync.next_login_notification, login_id)

    async def next_turn_notification(self, turn_id: str) -> Notification:
        """Wait for the next notification routed to one turn."""
        return await self._call_sync(self._sync.next_turn_notification, turn_id)

    async def next_goal_notification(self, state: _GoalOperationState) -> Notification:
        """Wait for the next notification in a logical goal turn."""
        return await self._call_sync(self._sync.next_goal_notification, state)

    async def wait_for_login_completed(
        self,
        login_id: str,
    ) -> AccountLoginCompletedNotification:
        """Wait for the completion notification routed to one login attempt."""
        return await self._call_sync(self._sync.wait_for_login_completed, login_id)

    async def wait_for_turn_completed(self, turn_id: str) -> TurnCompletedNotification:
        """Wait for the completion notification routed to one turn."""
        return await self._call_sync(self._sync.wait_for_turn_completed, turn_id)

    async def stream_text(
        self,
        thread_id: str,
        text: str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> AsyncIterator[AgentMessageDeltaNotification]:
        """Stream text deltas from one turn without monopolizing the event loop."""
        iterator = self._sync.stream_text(thread_id, text, params)
        while True:
            has_value, chunk = await asyncio.to_thread(
                self._next_from_iterator,
                iterator,
            )
            if not has_value:
                break
            yield chunk
