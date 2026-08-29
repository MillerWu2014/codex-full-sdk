from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

from ._approval_mode import (
    ApprovalMode as ApprovalMode,
    _approval_mode_override_settings,
    _approval_mode_settings,
)
from ._experimental import require_experimental_api
from ._initialize_metadata import validate_initialize_metadata
from ._inputs import (
    AudioInput as AudioInput,
    ImageInput as ImageInput,
    Input as Input,
    InputItem as InputItem,
    LocalAudioInput as LocalAudioInput,
    LocalImageInput as LocalImageInput,
    MentionInput as MentionInput,
    RunInput,
    SkillInput as SkillInput,
    TextInput as TextInput,
    _normalize_run_input,
    _to_wire_input,
)
from ._login import (
    AsyncChatgptLoginHandle,
    AsyncDeviceCodeLoginHandle,
    ChatgptLoginHandle,
    DeviceCodeLoginHandle,
    async_start_chatgpt_login,
    async_start_device_code_login,
    start_chatgpt_login,
    start_device_code_login,
)
from ._run import (
    TurnResult,
    _collect_async_turn_result,
    _collect_turn_result,
)
from ._sandbox import Sandbox as Sandbox, _sandbox_mode, _sandbox_policy
from .async_client import AsyncCodexClient
from .client import CodexClient, CodexConfig
from .generated.v2_all import (
    ApiKeyLoginAccountParams,
    CollaborationMode,
    CollaborationModeListResponse,
    ConfigBatchWriteParams,
    ConfigEdit,
    ConfigReadParams,
    ConfigReadResponse,
    ConfigRequirementsReadResponse,
    ConfigValueWriteParams,
    ConfigWriteResponse,
    ExperimentalFeatureEnablementSetParams,
    ExperimentalFeatureEnablementSetResponse,
    ExperimentalFeatureListParams,
    ExperimentalFeatureListResponse,
    ExternalAgentConfigDetectParams,
    ExternalAgentConfigDetectResponse,
    ExternalAgentConfigImportHistoriesReadResponse,
    ExternalAgentConfigImportParams,
    ExternalAgentConfigImportResponse,
    ExternalAgentConfigMigrationItem,
    FsChangedNotification,
    FsCopyParams,
    FsCopyResponse,
    FsCreateDirectoryParams,
    FsCreateDirectoryResponse,
    FsGetMetadataParams,
    FsGetMetadataResponse,
    FsReadDirectoryParams,
    FsReadDirectoryResponse,
    FsReadFileParams,
    FsReadFileResponse,
    FsRemoveParams,
    FsRemoveResponse,
    FsUnwatchParams,
    FsUnwatchResponse,
    FsWatchParams,
    FsWatchResponse,
    FsWriteFileParams,
    FsWriteFileResponse,
    FuzzyFileSearchParams,
    FuzzyFileSearchSessionStartParams,
    FuzzyFileSearchSessionStopParams,
    FuzzyFileSearchSessionUpdateParams,
    GetAccountParams,
    GetAccountResponse,
    ListMcpServerStatusParams,
    ListMcpServerStatusResponse,
    LoginAccountParams,
    McpResourceReadParams,
    McpResourceReadResponse,
    McpServerRefreshResponse,
    McpServerStatusDetail,
    McpServerToolCallParams,
    McpServerToolCallResponse,
    MemoryResetResponse,
    MergeStrategy,
    ModelListResponse,
    ModelProviderCapabilitiesReadResponse,
    Personality,
    PluginSkillReadParams,
    PluginSkillReadResponse,
    ProjectCreateParams,
    ProjectCreateResponse,
    ProjectDeleteParams,
    ProjectDeleteResponse,
    ProjectImportParams,
    ProjectImportResponse,
    ProjectListParams,
    ProjectListResponse,
    ProjectMoveParams,
    ProjectMoveResponse,
    ProjectReadParams,
    ProjectReadResponse,
    ProjectRoot,
    ProjectSortKey,
    ProjectUpdateParams,
    ProjectUpdateResponse,
    ReasoningEffort,
    ReasoningSummary,
    SkillsConfigWriteParams,
    SkillsConfigWriteResponse,
    SkillsExtraRootsSetParams,
    SkillsExtraRootsSetResponse,
    SkillsListParams,
    SkillsListResponse,
    SortDirection,
    ThreadArchiveResponse,
    ThreadCompactStartResponse,
    ThreadDeleteParams,
    ThreadDeleteResponse,
    ThreadForkParams,
    ThreadGoalClearResponse,
    ThreadGoalGetParams,
    ThreadGoalGetResponse,
    ThreadGoalSetResponse,
    ThreadGoalStatus,
    ThreadInjectItemsParams,
    ThreadInjectItemsResponse,
    ThreadItemsListParams,
    ThreadItemsListResponse,
    ThreadListCwdFilter,
    ThreadListParams,
    ThreadListResponse,
    ThreadLoadedListParams,
    ThreadLoadedListResponse,
    ThreadMemoryMode,
    ThreadMemoryModeSetParams,
    ThreadMemoryModeSetResponse,
    ThreadMetadataGitInfoUpdateParams,
    ThreadMetadataUpdateParams,
    ThreadMetadataUpdateResponse,
    ThreadQueueAddParams,
    ThreadQueueAddResponse,
    ThreadQueueDeleteParams,
    ThreadQueueDeleteResponse,
    ThreadQueueListParams,
    ThreadQueueListResponse,
    ThreadQueueReorderParams,
    ThreadQueueReorderResponse,
    ThreadQueueStartParams,
    ThreadQueueStartResponse,
    ThreadQueueUpdateParams,
    ThreadQueueUpdateResponse,
    ThreadReadResponse,
    ThreadResumeParams,
    ThreadRevertParams,
    ThreadRevertResponse,
    ThreadSearchOccurrencesParams,
    ThreadSearchOccurrencesResponse,
    ThreadSearchParams,
    ThreadSearchResponse,
    ThreadSearchSortKey,
    ThreadSectionAppearance,
    ThreadSectionCreateParams,
    ThreadSectionCreateResponse,
    ThreadSectionDeleteParams,
    ThreadSectionDeleteResponse,
    ThreadSectionListParams,
    ThreadSectionListResponse,
    ThreadSectionMoveParams,
    ThreadSectionMoveResponse,
    ThreadSectionUpdateParams,
    ThreadSectionUpdateResponse,
    ThreadSetNameResponse,
    ThreadSettingsUpdateParams,
    ThreadSettingsUpdateResponse,
    ThreadSortKey,
    ThreadSource,
    ThreadSourceKind,
    ThreadStartParams,
    ThreadStartSource,
    ThreadTurnsListParams,
    ThreadTurnsListResponse,
    ThreadUnsubscribeParams,
    ThreadUnsubscribeResponse,
    TurnCompletedNotification,
    TurnEnvironmentParams,
    TurnInterruptResponse,
    TurnItemsView,
    TurnSettingsUpdateParams,
    TurnSettingsUpdateResponse,
    TurnStartParams,
    TurnSteerResponse,
    TurnToolOutput,
)
from .models import InitializeResponse, JsonObject, JsonValue, Notification
from .types import (
    FuzzyFileSearchResponse,
    FuzzyFileSearchSessionStartResponse,
    FuzzyFileSearchSessionStopResponse,
    FuzzyFileSearchSessionUpdateResponse,
)

# Keep JsonValue in this module namespace so get_type_hints can resolve
# JsonObject's recursive forward references in generated method signatures.
globals()["JsonValue"] = JsonValue


@dataclass(slots=True)
class FsWatchHandle:
    """Iterator and context manager for one `fs/watch` subscription."""

    _client: CodexClient
    watch_id: str
    response: FsWatchResponse
    _closed: bool = False

    def __iter__(self) -> Iterator[FsChangedNotification]:
        return self

    def __next__(self) -> FsChangedNotification:
        if self._closed:
            raise StopIteration
        event = self._client.next_watch_notification(self.watch_id)
        if event is None:
            self._closed = True
            raise StopIteration
        payload = event.payload
        if isinstance(payload, FsChangedNotification):
            return payload
        raise TypeError(f"unexpected fs/changed payload: {type(payload)!r}")

    def close(self) -> None:
        """RPC: fs/unwatch."""
        if self._closed:
            return
        self._closed = True
        try:
            self._client.fs_unwatch(FsUnwatchParams(watch_id=self.watch_id))
        finally:
            self._client.unregister_watch_notifications(self.watch_id)

    def __enter__(self) -> FsWatchHandle:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()


@dataclass(slots=True)
class AsyncFsWatchHandle:
    """Async iterator and context manager for one `fs/watch` subscription."""

    _codex: AsyncCodex
    watch_id: str
    response: FsWatchResponse
    _closed: bool = False

    def __aiter__(self) -> AsyncIterator[FsChangedNotification]:
        return self

    async def __anext__(self) -> FsChangedNotification:
        if self._closed:
            raise StopAsyncIteration
        event = await self._codex._client.next_watch_notification(self.watch_id)
        if event is None:
            self._closed = True
            raise StopAsyncIteration
        payload = event.payload
        if isinstance(payload, FsChangedNotification):
            return payload
        raise TypeError(f"unexpected fs/changed payload: {type(payload)!r}")

    async def aclose(self) -> None:
        """RPC: fs/unwatch."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._codex._client.fs_unwatch(FsUnwatchParams(watch_id=self.watch_id))
        finally:
            self._codex._client.unregister_watch_notifications(self.watch_id)

    async def __aenter__(self) -> AsyncFsWatchHandle:
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        await self.aclose()


class ExperimentalCodex:
    """P1 experimental RPCs gated by ``CodexConfig.experimental_api``."""

    def __init__(self, client: CodexClient) -> None:
        self._client = client

    def thread_search(
        self,
        search_term: str,
        *,
        archived: bool | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ThreadSearchSortKey | None = None,
        source_kinds: list[ThreadSourceKind] | None = None,
    ) -> ThreadSearchResponse:
        """RPC: thread/search."""
        require_experimental_api(self._client.config, "thread/search")
        return self._client.thread_search(
            ThreadSearchParams(
                search_term=search_term,
                archived=archived,
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                sort_key=sort_key,
                source_kinds=source_kinds,
            )
        )

    def thread_search_occurrences(
        self,
        thread_id: str,
        search_term: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> ThreadSearchOccurrencesResponse:
        """RPC: thread/searchOccurrences."""
        require_experimental_api(self._client.config, "thread/searchOccurrences")
        return self._client.thread_search_occurrences(
            ThreadSearchOccurrencesParams(
                thread_id=thread_id,
                search_term=search_term,
                cursor=cursor,
                limit=limit,
            )
        )

    def collaboration_mode_list(self) -> CollaborationModeListResponse:
        """RPC: collaborationMode/list."""
        require_experimental_api(self._client.config, "collaborationMode/list")
        return self._client.collaboration_mode_list()

    def fuzzy_file_search_session_start(
        self, roots: list[str], *, session_id: str
    ) -> FuzzyFileSearchSessionStartResponse:
        """RPC: fuzzyFileSearch/sessionStart."""
        require_experimental_api(self._client.config, "fuzzyFileSearch/sessionStart")
        return self._client.fuzzy_file_search_session_start(
            FuzzyFileSearchSessionStartParams(roots=roots, session_id=session_id)
        )

    def fuzzy_file_search_session_update(
        self, session_id: str, query: str
    ) -> FuzzyFileSearchSessionUpdateResponse:
        """RPC: fuzzyFileSearch/sessionUpdate."""
        require_experimental_api(self._client.config, "fuzzyFileSearch/sessionUpdate")
        return self._client.fuzzy_file_search_session_update(
            FuzzyFileSearchSessionUpdateParams(session_id=session_id, query=query)
        )

    def fuzzy_file_search_session_stop(self, session_id: str) -> FuzzyFileSearchSessionStopResponse:
        """RPC: fuzzyFileSearch/sessionStop."""
        require_experimental_api(self._client.config, "fuzzyFileSearch/sessionStop")
        return self._client.fuzzy_file_search_session_stop(
            FuzzyFileSearchSessionStopParams(session_id=session_id)
        )

    def memory_reset(self) -> MemoryResetResponse:
        """RPC: memory/reset."""
        require_experimental_api(self._client.config, "memory/reset")
        return self._client.memory_reset()

    def project_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ProjectSortKey | None = None,
    ) -> ProjectListResponse:
        """RPC: project/list."""
        require_experimental_api(self._client.config, "project/list")
        return self._client.project_list(
            ProjectListParams(
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                sort_key=sort_key,
            )
        )

    def project_read(self, project_id: str) -> ProjectReadResponse:
        """RPC: project/read."""
        require_experimental_api(self._client.config, "project/read")
        return self._client.project_read(ProjectReadParams(project_id=project_id))

    def project_create(
        self,
        name: str,
        roots: list[ProjectRoot],
        *,
        idempotency_key: str,
        metadata: JsonObject | None = None,
    ) -> ProjectCreateResponse:
        """RPC: project/create."""
        require_experimental_api(self._client.config, "project/create")
        return self._client.project_create(
            ProjectCreateParams(
                name=name,
                roots=roots,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        )

    def project_import(
        self,
        name: str,
        roots: list[ProjectRoot],
        *,
        idempotency_key: str,
        metadata: JsonObject | None = None,
        threads: list[str] | None = None,
    ) -> ProjectImportResponse:
        """RPC: project/import."""
        require_experimental_api(self._client.config, "project/import")
        return self._client.project_import(
            ProjectImportParams(
                name=name,
                roots=roots,
                idempotency_key=idempotency_key,
                metadata=metadata,
                threads=threads,
            )
        )

    def project_update(
        self,
        project_id: str,
        *,
        metadata: JsonObject | None = None,
        name: str | None = None,
        roots: list[ProjectRoot] | None = None,
    ) -> ProjectUpdateResponse:
        """RPC: project/update."""
        require_experimental_api(self._client.config, "project/update")
        return self._client.project_update(
            ProjectUpdateParams(
                project_id=project_id,
                metadata=metadata,
                name=name,
                roots=roots,
            )
        )

    def project_move(
        self, project_id: str, *, before_project_id: str | None = None
    ) -> ProjectMoveResponse:
        """RPC: project/move."""
        require_experimental_api(self._client.config, "project/move")
        return self._client.project_move(
            ProjectMoveParams(project_id=project_id, before_project_id=before_project_id)
        )

    def project_delete(self, project_id: str) -> ProjectDeleteResponse:
        """RPC: project/delete."""
        require_experimental_api(self._client.config, "project/delete")
        return self._client.project_delete(ProjectDeleteParams(project_id=project_id))


class AsyncExperimentalCodex:
    """Async mirror of :class:`ExperimentalCodex`."""

    def __init__(self, codex: AsyncCodex) -> None:
        self._codex = codex

    async def thread_search(
        self,
        search_term: str,
        *,
        archived: bool | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ThreadSearchSortKey | None = None,
        source_kinds: list[ThreadSourceKind] | None = None,
    ) -> ThreadSearchResponse:
        """RPC: thread/search."""
        require_experimental_api(self._codex._client.config, "thread/search")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_search(
            ThreadSearchParams(
                search_term=search_term,
                archived=archived,
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                sort_key=sort_key,
                source_kinds=source_kinds,
            )
        )

    async def thread_search_occurrences(
        self,
        thread_id: str,
        search_term: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> ThreadSearchOccurrencesResponse:
        """RPC: thread/searchOccurrences."""
        require_experimental_api(self._codex._client.config, "thread/searchOccurrences")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_search_occurrences(
            ThreadSearchOccurrencesParams(
                thread_id=thread_id,
                search_term=search_term,
                cursor=cursor,
                limit=limit,
            )
        )

    async def collaboration_mode_list(self) -> CollaborationModeListResponse:
        """RPC: collaborationMode/list."""
        require_experimental_api(self._codex._client.config, "collaborationMode/list")
        await self._codex._ensure_initialized()
        return await self._codex._client.collaboration_mode_list()

    async def fuzzy_file_search_session_start(
        self, roots: list[str], *, session_id: str
    ) -> FuzzyFileSearchSessionStartResponse:
        """RPC: fuzzyFileSearch/sessionStart."""
        require_experimental_api(self._codex._client.config, "fuzzyFileSearch/sessionStart")
        await self._codex._ensure_initialized()
        return await self._codex._client.fuzzy_file_search_session_start(
            FuzzyFileSearchSessionStartParams(roots=roots, session_id=session_id)
        )

    async def fuzzy_file_search_session_update(
        self, session_id: str, query: str
    ) -> FuzzyFileSearchSessionUpdateResponse:
        """RPC: fuzzyFileSearch/sessionUpdate."""
        require_experimental_api(self._codex._client.config, "fuzzyFileSearch/sessionUpdate")
        await self._codex._ensure_initialized()
        return await self._codex._client.fuzzy_file_search_session_update(
            FuzzyFileSearchSessionUpdateParams(session_id=session_id, query=query)
        )

    async def fuzzy_file_search_session_stop(
        self, session_id: str
    ) -> FuzzyFileSearchSessionStopResponse:
        """RPC: fuzzyFileSearch/sessionStop."""
        require_experimental_api(self._codex._client.config, "fuzzyFileSearch/sessionStop")
        await self._codex._ensure_initialized()
        return await self._codex._client.fuzzy_file_search_session_stop(
            FuzzyFileSearchSessionStopParams(session_id=session_id)
        )

    async def memory_reset(self) -> MemoryResetResponse:
        """RPC: memory/reset."""
        require_experimental_api(self._codex._client.config, "memory/reset")
        await self._codex._ensure_initialized()
        return await self._codex._client.memory_reset()

    async def project_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ProjectSortKey | None = None,
    ) -> ProjectListResponse:
        """RPC: project/list."""
        require_experimental_api(self._codex._client.config, "project/list")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_list(
            ProjectListParams(
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                sort_key=sort_key,
            )
        )

    async def project_read(self, project_id: str) -> ProjectReadResponse:
        """RPC: project/read."""
        require_experimental_api(self._codex._client.config, "project/read")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_read(ProjectReadParams(project_id=project_id))

    async def project_create(
        self,
        name: str,
        roots: list[ProjectRoot],
        *,
        idempotency_key: str,
        metadata: JsonObject | None = None,
    ) -> ProjectCreateResponse:
        """RPC: project/create."""
        require_experimental_api(self._codex._client.config, "project/create")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_create(
            ProjectCreateParams(
                name=name,
                roots=roots,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        )

    async def project_import(
        self,
        name: str,
        roots: list[ProjectRoot],
        *,
        idempotency_key: str,
        metadata: JsonObject | None = None,
        threads: list[str] | None = None,
    ) -> ProjectImportResponse:
        """RPC: project/import."""
        require_experimental_api(self._codex._client.config, "project/import")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_import(
            ProjectImportParams(
                name=name,
                roots=roots,
                idempotency_key=idempotency_key,
                metadata=metadata,
                threads=threads,
            )
        )

    async def project_update(
        self,
        project_id: str,
        *,
        metadata: JsonObject | None = None,
        name: str | None = None,
        roots: list[ProjectRoot] | None = None,
    ) -> ProjectUpdateResponse:
        """RPC: project/update."""
        require_experimental_api(self._codex._client.config, "project/update")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_update(
            ProjectUpdateParams(
                project_id=project_id,
                metadata=metadata,
                name=name,
                roots=roots,
            )
        )

    async def project_move(
        self, project_id: str, *, before_project_id: str | None = None
    ) -> ProjectMoveResponse:
        """RPC: project/move."""
        require_experimental_api(self._codex._client.config, "project/move")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_move(
            ProjectMoveParams(project_id=project_id, before_project_id=before_project_id)
        )

    async def project_delete(self, project_id: str) -> ProjectDeleteResponse:
        """RPC: project/delete."""
        require_experimental_api(self._codex._client.config, "project/delete")
        await self._codex._ensure_initialized()
        return await self._codex._client.project_delete(ProjectDeleteParams(project_id=project_id))


class Codex:
    """Synchronous client for creating threads and running Codex turns.

    The client starts its runtime connection during construction. Use it as a
    context manager so resources are closed promptly.
    """

    def __init__(self, config: CodexConfig | None = None) -> None:
        self._client = CodexClient(config=config)
        try:
            self._client.start()
            self._init = validate_initialize_metadata(self._client.initialize())
        except Exception:
            self._client.close()
            raise

    def __enter__(self) -> "Codex":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    @property
    def metadata(self) -> InitializeResponse:
        return self._init

    def close(self) -> None:
        self._client.close()

    def login_api_key(self, api_key: str) -> None:
        """Authenticate Codex with an API key."""
        self._client.account_login_start(
            LoginAccountParams(
                root=ApiKeyLoginAccountParams(
                    api_key=api_key,
                    type="apiKey",
                )
            )
        )

    def login_chatgpt(self) -> ChatgptLoginHandle:
        """Start browser-based ChatGPT login and return its live handle."""
        return start_chatgpt_login(self._client)

    def login_chatgpt_device_code(self) -> DeviceCodeLoginHandle:
        """Start device-code ChatGPT login and return its live handle."""
        return start_device_code_login(self._client)

    def account(self, *, refresh_token: bool = False) -> GetAccountResponse:
        """Read the current Codex account state."""
        return self._client.account_read(GetAccountParams(refresh_token=refresh_token))

    def logout(self) -> None:
        """Clear the current Codex account session."""
        self._client.account_logout()

    # BEGIN GENERATED: Codex.flat_methods
    def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        base_instructions: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_name: str | None = None,
        service_tier: str | None = None,
        session_start_source: ThreadStartSource | None = None,
        thread_source: ThreadSource | None = None,
    ) -> Thread:
        """Create a new Codex conversation thread."""
        if environments is not None:
            require_experimental_api(self._client.config, "environments")
        approval_policy, approvals_reviewer = _approval_mode_settings(approval_mode)
        params = ThreadStartParams(
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            environments=environments,
            ephemeral=ephemeral,
            model=model,
            model_provider=model_provider,
            personality=personality,
            sandbox=_sandbox_mode(sandbox),
            service_name=service_name,
            service_tier=service_tier,
            session_start_source=session_start_source,
            thread_source=thread_source,
        )
        started = self._client.thread_start(params)
        return Thread(self._client, started.thread.id)

    def thread_list(
        self,
        *,
        archived: bool | None = None,
        cursor: str | None = None,
        cwd: ThreadListCwdFilter | None = None,
        limit: int | None = None,
        model_providers: list[str] | None = None,
        search_term: str | None = None,
        section_id: str | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ThreadSortKey | None = None,
        source_kinds: list[ThreadSourceKind] | None = None,
        use_state_db_only: bool | None = None,
    ) -> ThreadListResponse:
        """List saved conversation threads."""
        params = ThreadListParams(
            archived=archived,
            cursor=cursor,
            cwd=cwd,
            limit=limit,
            model_providers=model_providers,
            search_term=search_term,
            section_id=section_id,
            sort_direction=sort_direction,
            sort_key=sort_key,
            source_kinds=source_kinds,
            use_state_db_only=use_state_db_only,
        )
        return self._client.thread_list(params)

    def thread_resume(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        exclude_turns: bool | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
    ) -> Thread:
        """Resume an existing conversation thread by ID."""
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = ThreadResumeParams(
            thread_id=thread_id,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            exclude_turns=exclude_turns,
            model=model,
            model_provider=model_provider,
            personality=personality,
            sandbox=_sandbox_mode(sandbox),
            service_tier=service_tier,
        )
        resumed = self._client.thread_resume(thread_id, params)
        return Thread(self._client, resumed.thread.id)

    def thread_fork(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        before_turn_id: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        ephemeral: bool | None = None,
        exclude_turns: bool | None = None,
        last_turn_id: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        thread_source: ThreadSource | None = None,
    ) -> Thread:
        """Create a new thread from an existing thread."""
        if before_turn_id is not None:
            require_experimental_api(self._client.config, "before_turn_id")
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = ThreadForkParams(
            thread_id=thread_id,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            before_turn_id=before_turn_id,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            ephemeral=ephemeral,
            exclude_turns=exclude_turns,
            last_turn_id=last_turn_id,
            model=model,
            model_provider=model_provider,
            sandbox=_sandbox_mode(sandbox),
            service_tier=service_tier,
            thread_source=thread_source,
        )
        forked = self._client.thread_fork(thread_id, params)
        return Thread(self._client, forked.thread.id)

    def thread_archive(self, thread_id: str) -> ThreadArchiveResponse:
        """Archive a stored conversation thread."""
        return self._client.thread_archive(thread_id)

    def thread_unarchive(self, thread_id: str) -> Thread:
        """Restore an archived conversation thread."""
        unarchived = self._client.thread_unarchive(thread_id)
        return Thread(self._client, unarchived.thread.id)

    # END GENERATED: Codex.flat_methods

    def models(self, *, include_hidden: bool = False) -> ModelListResponse:
        """List available models reported by Codex."""
        return self._client.model_list(include_hidden=include_hidden)

    @property
    def experimental(self) -> ExperimentalCodex:
        """P1 experimental RPCs that require ``experimental_api=True``."""
        return ExperimentalCodex(self._client)

    def thread_delete(self, thread_id: str) -> ThreadDeleteResponse:
        """RPC: thread/delete."""
        return self._client.thread_delete(ThreadDeleteParams(thread_id=thread_id))

    def thread_loaded_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadLoadedListResponse:
        """RPC: thread/loaded/list."""
        return self._client.thread_loaded_list(ThreadLoadedListParams(cursor=cursor, limit=limit))

    def thread_section_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadSectionListResponse:
        """RPC: threadSection/list."""
        return self._client.thread_section_list(ThreadSectionListParams(cursor=cursor, limit=limit))

    def thread_section_create(
        self, name: str, *, appearance: ThreadSectionAppearance | None = None
    ) -> ThreadSectionCreateResponse:
        """RPC: threadSection/create."""
        return self._client.thread_section_create(
            ThreadSectionCreateParams(name=name, appearance=appearance)
        )

    def thread_section_update(
        self,
        section_id: str,
        name: str,
        *,
        appearance: ThreadSectionAppearance | None = None,
    ) -> ThreadSectionUpdateResponse:
        """RPC: threadSection/update."""
        return self._client.thread_section_update(
            ThreadSectionUpdateParams(section_id=section_id, name=name, appearance=appearance)
        )

    def thread_section_delete(self, section_id: str) -> ThreadSectionDeleteResponse:
        """RPC: threadSection/delete."""
        return self._client.thread_section_delete(ThreadSectionDeleteParams(section_id=section_id))

    def skills_list(
        self, *, cwds: list[str] | None = None, force_reload: bool | None = None
    ) -> SkillsListResponse:
        """RPC: skills/list."""
        return self._client.skills_list(SkillsListParams(cwds=cwds, force_reload=force_reload))

    def skills_extra_roots_set(self, extra_roots: list[str]) -> SkillsExtraRootsSetResponse:
        """RPC: skills/extraRoots/set."""
        return self._client.skills_extra_roots_set(
            SkillsExtraRootsSetParams(extra_roots=extra_roots)
        )

    def skills_config_write(
        self, enabled: bool, *, name: str | None = None, path: str | None = None
    ) -> SkillsConfigWriteResponse:
        """RPC: skills/config/write."""
        return self._client.skills_config_write(
            SkillsConfigWriteParams(enabled=enabled, name=name, path=path)
        )

    def plugin_skill_read(
        self, remote_marketplace_name: str, remote_plugin_id: str, skill_name: str
    ) -> PluginSkillReadResponse:
        """RPC: plugin/skill/read."""
        return self._client.plugin_skill_read(
            PluginSkillReadParams(
                remote_marketplace_name=remote_marketplace_name,
                remote_plugin_id=remote_plugin_id,
                skill_name=skill_name,
            )
        )

    def mcp_reload(self) -> McpServerRefreshResponse:
        """RPC: config/mcpServer/reload."""
        return self._client.mcp_reload()

    def mcp_status_list(
        self,
        *,
        cursor: str | None = None,
        detail: McpServerStatusDetail | None = None,
        limit: int | None = None,
        thread_id: str | None = None,
    ) -> ListMcpServerStatusResponse:
        """RPC: mcpServerStatus/list."""
        return self._client.mcp_status_list(
            ListMcpServerStatusParams(
                cursor=cursor, detail=detail, limit=limit, thread_id=thread_id
            )
        )

    def mcp_resource_read(
        self,
        server: str,
        uri: str,
        *,
        connector_id: str | None = None,
        origin_call_id: str | None = None,
        thread_id: str | None = None,
    ) -> McpResourceReadResponse:
        """RPC: mcpServer/resource/read."""
        return self._client.mcp_resource_read(
            McpResourceReadParams(
                server=server,
                uri=uri,
                connector_id=connector_id,
                origin_call_id=origin_call_id,
                thread_id=thread_id,
            )
        )

    def config_read(
        self, *, cwd: str | None = None, include_layers: bool | None = None
    ) -> ConfigReadResponse:
        """RPC: config/read."""
        return self._client.config_read(ConfigReadParams(cwd=cwd, include_layers=include_layers))

    def config_value_write(
        self,
        key_path: str,
        value: object,
        merge_strategy: MergeStrategy,
        *,
        expected_version: str | None = None,
        file_path: str | None = None,
    ) -> ConfigWriteResponse:
        """RPC: config/value/write."""
        return self._client.config_value_write(
            ConfigValueWriteParams(
                key_path=key_path,
                value=value,
                merge_strategy=merge_strategy,
                expected_version=expected_version,
                file_path=file_path,
            )
        )

    def config_batch_write(
        self,
        edits: list[ConfigEdit],
        *,
        expected_version: str | None = None,
        file_path: str | None = None,
        reload_user_config: bool | None = None,
    ) -> ConfigWriteResponse:
        """RPC: config/batchWrite."""
        return self._client.config_batch_write(
            ConfigBatchWriteParams(
                edits=edits,
                expected_version=expected_version,
                file_path=file_path,
                reload_user_config=reload_user_config,
            )
        )

    def config_requirements_read(self) -> ConfigRequirementsReadResponse:
        """RPC: configRequirements/read."""
        return self._client.config_requirements_read()

    def experimental_feature_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        thread_id: str | None = None,
    ) -> ExperimentalFeatureListResponse:
        """RPC: experimentalFeature/list."""
        return self._client.experimental_feature_list(
            ExperimentalFeatureListParams(cursor=cursor, limit=limit, thread_id=thread_id)
        )

    def experimental_feature_enablement_set(
        self, enablement: dict[str, bool]
    ) -> ExperimentalFeatureEnablementSetResponse:
        """RPC: experimentalFeature/enablement/set."""
        return self._client.experimental_feature_enablement_set(
            ExperimentalFeatureEnablementSetParams(enablement=enablement)
        )

    def external_agent_config_detect(
        self,
        *,
        cwds: list[str] | None = None,
        include_home: bool | None = None,
        max_session_age_days: int | None = None,
        max_sessions: int | None = None,
        migration_source: str | None = None,
        source: str | None = None,
    ) -> ExternalAgentConfigDetectResponse:
        """RPC: externalAgentConfig/detect."""
        return self._client.external_agent_config_detect(
            ExternalAgentConfigDetectParams(
                cwds=cwds,
                include_home=include_home,
                max_session_age_days=max_session_age_days,
                max_sessions=max_sessions,
                migration_source=migration_source,
                source=source,
            )
        )

    def external_agent_config_import(
        self,
        migration_items: list[ExternalAgentConfigMigrationItem],
        *,
        migration_source: str | None = None,
        provider_id: str | None = None,
        source: str | None = None,
    ) -> ExternalAgentConfigImportResponse:
        """RPC: externalAgentConfig/import."""
        return self._client.external_agent_config_import(
            ExternalAgentConfigImportParams(
                migration_items=migration_items,
                migration_source=migration_source,
                provider_id=provider_id,
                source=source,
            )
        )

    def external_agent_config_import_read_histories(
        self,
    ) -> ExternalAgentConfigImportHistoriesReadResponse:
        """RPC: externalAgentConfig/import/readHistories."""
        return self._client.external_agent_config_import_read_histories()

    def model_provider_capabilities(self) -> ModelProviderCapabilitiesReadResponse:
        """RPC: modelProvider/capabilities/read."""
        return self._client.model_provider_capabilities()

    def fs_read_file(self, path: str) -> FsReadFileResponse:
        """RPC: fs/readFile."""
        return self._client.fs_read_file(FsReadFileParams(path=path))

    def fs_write_file(self, path: str, data_base64: str) -> FsWriteFileResponse:
        """RPC: fs/writeFile."""
        return self._client.fs_write_file(FsWriteFileParams(path=path, data_base64=data_base64))

    def fs_create_directory(
        self, path: str, *, recursive: bool | None = None
    ) -> FsCreateDirectoryResponse:
        """RPC: fs/createDirectory."""
        return self._client.fs_create_directory(
            FsCreateDirectoryParams(path=path, recursive=recursive)
        )

    def fs_get_metadata(self, path: str) -> FsGetMetadataResponse:
        """RPC: fs/getMetadata."""
        return self._client.fs_get_metadata(FsGetMetadataParams(path=path))

    def fs_read_directory(self, path: str) -> FsReadDirectoryResponse:
        """RPC: fs/readDirectory."""
        return self._client.fs_read_directory(FsReadDirectoryParams(path=path))

    def fs_remove(
        self, path: str, *, force: bool | None = None, recursive: bool | None = None
    ) -> FsRemoveResponse:
        """RPC: fs/remove."""
        return self._client.fs_remove(FsRemoveParams(path=path, force=force, recursive=recursive))

    def fs_copy(
        self, source_path: str, destination_path: str, *, recursive: bool | None = None
    ) -> FsCopyResponse:
        """RPC: fs/copy."""
        return self._client.fs_copy(
            FsCopyParams(
                source_path=source_path,
                destination_path=destination_path,
                recursive=recursive,
            )
        )

    def fs_watch(self, path: str, *, watch_id: str | None = None) -> FsWatchHandle:
        """RPC: fs/watch.

        Requires ``experimental_api=True`` as an SDK staging gate; the protocol
        currently marks this method stable.
        """
        require_experimental_api(self._client.config, "fs/watch")
        resolved_watch_id = watch_id or str(uuid.uuid4())
        self._client.register_watch_notifications(resolved_watch_id)
        try:
            response = self._client.fs_watch(FsWatchParams(path=path, watch_id=resolved_watch_id))
        except BaseException:
            self._client.unregister_watch_notifications(resolved_watch_id)
            raise
        return FsWatchHandle(self._client, resolved_watch_id, response)

    def fs_unwatch(self, watch_id: str) -> FsUnwatchResponse:
        """RPC: fs/unwatch.

        Requires ``experimental_api=True`` as an SDK staging gate; the protocol
        currently marks this method stable.
        """
        require_experimental_api(self._client.config, "fs/unwatch")
        try:
            return self._client.fs_unwatch(FsUnwatchParams(watch_id=watch_id))
        finally:
            self._client.unregister_watch_notifications(watch_id)

    def fuzzy_file_search(
        self,
        query: str,
        roots: list[str],
        *,
        cancellation_token: str | None = None,
    ) -> FuzzyFileSearchResponse:
        """RPC: fuzzyFileSearch."""
        return self._client.fuzzy_file_search(
            FuzzyFileSearchParams(query=query, roots=roots, cancellation_token=cancellation_token)
        )


class AsyncCodex:
    """Async mirror of :class:`Codex`.

    Prefer ``async with AsyncCodex()`` so initialization and shutdown are
    explicit and paired. The async client initializes lazily on context entry
    or first awaited API use.
    """

    def __init__(self, config: CodexConfig | None = None) -> None:
        self._client = AsyncCodexClient(config=config)
        self._init: InitializeResponse | None = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def __aenter__(self) -> "AsyncCodex":
        await self._ensure_initialized()
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        await self.close()

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                await self._client.start()
                payload = await self._client.initialize()
                self._init = validate_initialize_metadata(payload)
                self._initialized = True
            except Exception:
                await self._client.close()
                self._init = None
                self._initialized = False
                raise

    @property
    def metadata(self) -> InitializeResponse:
        if self._init is None:
            raise RuntimeError(
                "AsyncCodex is not initialized yet. Prefer `async with AsyncCodex()`; "
                "initialization also happens on first awaited API use."
            )
        return self._init

    async def close(self) -> None:
        await self._client.close()
        self._init = None
        self._initialized = False

    async def login_api_key(self, api_key: str) -> None:
        """Authenticate Codex with an API key."""
        await self._ensure_initialized()
        await self._client.account_login_start(
            LoginAccountParams(
                root=ApiKeyLoginAccountParams(
                    api_key=api_key,
                    type="apiKey",
                )
            )
        )

    async def login_chatgpt(self) -> AsyncChatgptLoginHandle:
        """Start browser-based ChatGPT login and return its live handle."""
        await self._ensure_initialized()
        return await async_start_chatgpt_login(self)

    async def login_chatgpt_device_code(self) -> AsyncDeviceCodeLoginHandle:
        """Start device-code ChatGPT login and return its live handle."""
        await self._ensure_initialized()
        return await async_start_device_code_login(self)

    async def account(self, *, refresh_token: bool = False) -> GetAccountResponse:
        """Read the current Codex account state."""
        await self._ensure_initialized()
        return await self._client.account_read(GetAccountParams(refresh_token=refresh_token))

    async def logout(self) -> None:
        """Clear the current Codex account session."""
        await self._ensure_initialized()
        await self._client.account_logout()

    # BEGIN GENERATED: AsyncCodex.flat_methods
    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        base_instructions: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_name: str | None = None,
        service_tier: str | None = None,
        session_start_source: ThreadStartSource | None = None,
        thread_source: ThreadSource | None = None,
    ) -> AsyncThread:
        """Create a new Codex conversation thread."""
        if environments is not None:
            require_experimental_api(self._client.config, "environments")
        await self._ensure_initialized()
        approval_policy, approvals_reviewer = _approval_mode_settings(approval_mode)
        params = ThreadStartParams(
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            environments=environments,
            ephemeral=ephemeral,
            model=model,
            model_provider=model_provider,
            personality=personality,
            sandbox=_sandbox_mode(sandbox),
            service_name=service_name,
            service_tier=service_tier,
            session_start_source=session_start_source,
            thread_source=thread_source,
        )
        started = await self._client.thread_start(params)
        return AsyncThread(self, started.thread.id)

    async def thread_list(
        self,
        *,
        archived: bool | None = None,
        cursor: str | None = None,
        cwd: ThreadListCwdFilter | None = None,
        limit: int | None = None,
        model_providers: list[str] | None = None,
        search_term: str | None = None,
        section_id: str | None = None,
        sort_direction: SortDirection | None = None,
        sort_key: ThreadSortKey | None = None,
        source_kinds: list[ThreadSourceKind] | None = None,
        use_state_db_only: bool | None = None,
    ) -> ThreadListResponse:
        """List saved conversation threads."""
        await self._ensure_initialized()
        params = ThreadListParams(
            archived=archived,
            cursor=cursor,
            cwd=cwd,
            limit=limit,
            model_providers=model_providers,
            search_term=search_term,
            section_id=section_id,
            sort_direction=sort_direction,
            sort_key=sort_key,
            source_kinds=source_kinds,
            use_state_db_only=use_state_db_only,
        )
        return await self._client.thread_list(params)

    async def thread_resume(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        exclude_turns: bool | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
    ) -> AsyncThread:
        """Resume an existing conversation thread by ID."""
        await self._ensure_initialized()
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = ThreadResumeParams(
            thread_id=thread_id,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            exclude_turns=exclude_turns,
            model=model,
            model_provider=model_provider,
            personality=personality,
            sandbox=_sandbox_mode(sandbox),
            service_tier=service_tier,
        )
        resumed = await self._client.thread_resume(thread_id, params)
        return AsyncThread(self, resumed.thread.id)

    async def thread_fork(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        before_turn_id: str | None = None,
        config: JsonObject | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        ephemeral: bool | None = None,
        exclude_turns: bool | None = None,
        last_turn_id: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        thread_source: ThreadSource | None = None,
    ) -> AsyncThread:
        """Create a new thread from an existing thread."""
        if before_turn_id is not None:
            require_experimental_api(self._client.config, "before_turn_id")
        await self._ensure_initialized()
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = ThreadForkParams(
            thread_id=thread_id,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            base_instructions=base_instructions,
            before_turn_id=before_turn_id,
            config=config,
            cwd=cwd,
            developer_instructions=developer_instructions,
            ephemeral=ephemeral,
            exclude_turns=exclude_turns,
            last_turn_id=last_turn_id,
            model=model,
            model_provider=model_provider,
            sandbox=_sandbox_mode(sandbox),
            service_tier=service_tier,
            thread_source=thread_source,
        )
        forked = await self._client.thread_fork(thread_id, params)
        return AsyncThread(self, forked.thread.id)

    async def thread_archive(self, thread_id: str) -> ThreadArchiveResponse:
        """Archive a stored conversation thread."""
        await self._ensure_initialized()
        return await self._client.thread_archive(thread_id)

    async def thread_unarchive(self, thread_id: str) -> AsyncThread:
        """Restore an archived conversation thread."""
        await self._ensure_initialized()
        unarchived = await self._client.thread_unarchive(thread_id)
        return AsyncThread(self, unarchived.thread.id)

    # END GENERATED: AsyncCodex.flat_methods

    async def models(self, *, include_hidden: bool = False) -> ModelListResponse:
        await self._ensure_initialized()
        return await self._client.model_list(include_hidden=include_hidden)

    @property
    def experimental(self) -> AsyncExperimentalCodex:
        """P1 experimental RPCs that require ``experimental_api=True``."""
        return AsyncExperimentalCodex(self)

    async def thread_delete(self, thread_id: str) -> ThreadDeleteResponse:
        """RPC: thread/delete."""
        await self._ensure_initialized()
        return await self._client.thread_delete(ThreadDeleteParams(thread_id=thread_id))

    async def thread_loaded_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadLoadedListResponse:
        """RPC: thread/loaded/list."""
        await self._ensure_initialized()
        return await self._client.thread_loaded_list(
            ThreadLoadedListParams(cursor=cursor, limit=limit)
        )

    async def thread_section_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadSectionListResponse:
        """RPC: threadSection/list."""
        await self._ensure_initialized()
        return await self._client.thread_section_list(
            ThreadSectionListParams(cursor=cursor, limit=limit)
        )

    async def thread_section_create(
        self, name: str, *, appearance: ThreadSectionAppearance | None = None
    ) -> ThreadSectionCreateResponse:
        """RPC: threadSection/create."""
        await self._ensure_initialized()
        return await self._client.thread_section_create(
            ThreadSectionCreateParams(name=name, appearance=appearance)
        )

    async def thread_section_update(
        self,
        section_id: str,
        name: str,
        *,
        appearance: ThreadSectionAppearance | None = None,
    ) -> ThreadSectionUpdateResponse:
        """RPC: threadSection/update."""
        await self._ensure_initialized()
        return await self._client.thread_section_update(
            ThreadSectionUpdateParams(section_id=section_id, name=name, appearance=appearance)
        )

    async def thread_section_delete(self, section_id: str) -> ThreadSectionDeleteResponse:
        """RPC: threadSection/delete."""
        await self._ensure_initialized()
        return await self._client.thread_section_delete(
            ThreadSectionDeleteParams(section_id=section_id)
        )

    async def skills_list(
        self, *, cwds: list[str] | None = None, force_reload: bool | None = None
    ) -> SkillsListResponse:
        """RPC: skills/list."""
        await self._ensure_initialized()
        return await self._client.skills_list(
            SkillsListParams(cwds=cwds, force_reload=force_reload)
        )

    async def skills_extra_roots_set(self, extra_roots: list[str]) -> SkillsExtraRootsSetResponse:
        """RPC: skills/extraRoots/set."""
        await self._ensure_initialized()
        return await self._client.skills_extra_roots_set(
            SkillsExtraRootsSetParams(extra_roots=extra_roots)
        )

    async def skills_config_write(
        self, enabled: bool, *, name: str | None = None, path: str | None = None
    ) -> SkillsConfigWriteResponse:
        """RPC: skills/config/write."""
        await self._ensure_initialized()
        return await self._client.skills_config_write(
            SkillsConfigWriteParams(enabled=enabled, name=name, path=path)
        )

    async def plugin_skill_read(
        self, remote_marketplace_name: str, remote_plugin_id: str, skill_name: str
    ) -> PluginSkillReadResponse:
        """RPC: plugin/skill/read."""
        await self._ensure_initialized()
        return await self._client.plugin_skill_read(
            PluginSkillReadParams(
                remote_marketplace_name=remote_marketplace_name,
                remote_plugin_id=remote_plugin_id,
                skill_name=skill_name,
            )
        )

    async def mcp_reload(self) -> McpServerRefreshResponse:
        """RPC: config/mcpServer/reload."""
        await self._ensure_initialized()
        return await self._client.mcp_reload()

    async def mcp_status_list(
        self,
        *,
        cursor: str | None = None,
        detail: McpServerStatusDetail | None = None,
        limit: int | None = None,
        thread_id: str | None = None,
    ) -> ListMcpServerStatusResponse:
        """RPC: mcpServerStatus/list."""
        await self._ensure_initialized()
        return await self._client.mcp_status_list(
            ListMcpServerStatusParams(
                cursor=cursor, detail=detail, limit=limit, thread_id=thread_id
            )
        )

    async def mcp_resource_read(
        self,
        server: str,
        uri: str,
        *,
        connector_id: str | None = None,
        origin_call_id: str | None = None,
        thread_id: str | None = None,
    ) -> McpResourceReadResponse:
        """RPC: mcpServer/resource/read."""
        await self._ensure_initialized()
        return await self._client.mcp_resource_read(
            McpResourceReadParams(
                server=server,
                uri=uri,
                connector_id=connector_id,
                origin_call_id=origin_call_id,
                thread_id=thread_id,
            )
        )

    async def config_read(
        self, *, cwd: str | None = None, include_layers: bool | None = None
    ) -> ConfigReadResponse:
        """RPC: config/read."""
        await self._ensure_initialized()
        return await self._client.config_read(
            ConfigReadParams(cwd=cwd, include_layers=include_layers)
        )

    async def config_value_write(
        self,
        key_path: str,
        value: object,
        merge_strategy: MergeStrategy,
        *,
        expected_version: str | None = None,
        file_path: str | None = None,
    ) -> ConfigWriteResponse:
        """RPC: config/value/write."""
        await self._ensure_initialized()
        return await self._client.config_value_write(
            ConfigValueWriteParams(
                key_path=key_path,
                value=value,
                merge_strategy=merge_strategy,
                expected_version=expected_version,
                file_path=file_path,
            )
        )

    async def config_batch_write(
        self,
        edits: list[ConfigEdit],
        *,
        expected_version: str | None = None,
        file_path: str | None = None,
        reload_user_config: bool | None = None,
    ) -> ConfigWriteResponse:
        """RPC: config/batchWrite."""
        await self._ensure_initialized()
        return await self._client.config_batch_write(
            ConfigBatchWriteParams(
                edits=edits,
                expected_version=expected_version,
                file_path=file_path,
                reload_user_config=reload_user_config,
            )
        )

    async def config_requirements_read(self) -> ConfigRequirementsReadResponse:
        """RPC: configRequirements/read."""
        await self._ensure_initialized()
        return await self._client.config_requirements_read()

    async def experimental_feature_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        thread_id: str | None = None,
    ) -> ExperimentalFeatureListResponse:
        """RPC: experimentalFeature/list."""
        await self._ensure_initialized()
        return await self._client.experimental_feature_list(
            ExperimentalFeatureListParams(cursor=cursor, limit=limit, thread_id=thread_id)
        )

    async def experimental_feature_enablement_set(
        self, enablement: dict[str, bool]
    ) -> ExperimentalFeatureEnablementSetResponse:
        """RPC: experimentalFeature/enablement/set."""
        await self._ensure_initialized()
        return await self._client.experimental_feature_enablement_set(
            ExperimentalFeatureEnablementSetParams(enablement=enablement)
        )

    async def external_agent_config_detect(
        self,
        *,
        cwds: list[str] | None = None,
        include_home: bool | None = None,
        max_session_age_days: int | None = None,
        max_sessions: int | None = None,
        migration_source: str | None = None,
        source: str | None = None,
    ) -> ExternalAgentConfigDetectResponse:
        """RPC: externalAgentConfig/detect."""
        await self._ensure_initialized()
        return await self._client.external_agent_config_detect(
            ExternalAgentConfigDetectParams(
                cwds=cwds,
                include_home=include_home,
                max_session_age_days=max_session_age_days,
                max_sessions=max_sessions,
                migration_source=migration_source,
                source=source,
            )
        )

    async def external_agent_config_import(
        self,
        migration_items: list[ExternalAgentConfigMigrationItem],
        *,
        migration_source: str | None = None,
        provider_id: str | None = None,
        source: str | None = None,
    ) -> ExternalAgentConfigImportResponse:
        """RPC: externalAgentConfig/import."""
        await self._ensure_initialized()
        return await self._client.external_agent_config_import(
            ExternalAgentConfigImportParams(
                migration_items=migration_items,
                migration_source=migration_source,
                provider_id=provider_id,
                source=source,
            )
        )

    async def external_agent_config_import_read_histories(
        self,
    ) -> ExternalAgentConfigImportHistoriesReadResponse:
        """RPC: externalAgentConfig/import/readHistories."""
        await self._ensure_initialized()
        return await self._client.external_agent_config_import_read_histories()

    async def model_provider_capabilities(self) -> ModelProviderCapabilitiesReadResponse:
        """RPC: modelProvider/capabilities/read."""
        await self._ensure_initialized()
        return await self._client.model_provider_capabilities()

    async def fs_read_file(self, path: str) -> FsReadFileResponse:
        """RPC: fs/readFile."""
        await self._ensure_initialized()
        return await self._client.fs_read_file(FsReadFileParams(path=path))

    async def fs_write_file(self, path: str, data_base64: str) -> FsWriteFileResponse:
        """RPC: fs/writeFile."""
        await self._ensure_initialized()
        return await self._client.fs_write_file(
            FsWriteFileParams(path=path, data_base64=data_base64)
        )

    async def fs_create_directory(
        self, path: str, *, recursive: bool | None = None
    ) -> FsCreateDirectoryResponse:
        """RPC: fs/createDirectory."""
        await self._ensure_initialized()
        return await self._client.fs_create_directory(
            FsCreateDirectoryParams(path=path, recursive=recursive)
        )

    async def fs_get_metadata(self, path: str) -> FsGetMetadataResponse:
        """RPC: fs/getMetadata."""
        await self._ensure_initialized()
        return await self._client.fs_get_metadata(FsGetMetadataParams(path=path))

    async def fs_read_directory(self, path: str) -> FsReadDirectoryResponse:
        """RPC: fs/readDirectory."""
        await self._ensure_initialized()
        return await self._client.fs_read_directory(FsReadDirectoryParams(path=path))

    async def fs_remove(
        self, path: str, *, force: bool | None = None, recursive: bool | None = None
    ) -> FsRemoveResponse:
        """RPC: fs/remove."""
        await self._ensure_initialized()
        return await self._client.fs_remove(
            FsRemoveParams(path=path, force=force, recursive=recursive)
        )

    async def fs_copy(
        self, source_path: str, destination_path: str, *, recursive: bool | None = None
    ) -> FsCopyResponse:
        """RPC: fs/copy."""
        await self._ensure_initialized()
        return await self._client.fs_copy(
            FsCopyParams(
                source_path=source_path,
                destination_path=destination_path,
                recursive=recursive,
            )
        )

    async def fs_watch(self, path: str, *, watch_id: str | None = None) -> AsyncFsWatchHandle:
        """RPC: fs/watch.

        Requires ``experimental_api=True`` as an SDK staging gate; the protocol
        currently marks this method stable.
        """
        require_experimental_api(self._client.config, "fs/watch")
        await self._ensure_initialized()
        resolved_watch_id = watch_id or str(uuid.uuid4())
        self._client.register_watch_notifications(resolved_watch_id)
        try:
            response = await self._client.fs_watch(
                FsWatchParams(path=path, watch_id=resolved_watch_id)
            )
        except BaseException:
            self._client.unregister_watch_notifications(resolved_watch_id)
            raise
        return AsyncFsWatchHandle(self, resolved_watch_id, response)

    async def fs_unwatch(self, watch_id: str) -> FsUnwatchResponse:
        """RPC: fs/unwatch.

        Requires ``experimental_api=True`` as an SDK staging gate; the protocol
        currently marks this method stable.
        """
        require_experimental_api(self._client.config, "fs/unwatch")
        await self._ensure_initialized()
        try:
            return await self._client.fs_unwatch(FsUnwatchParams(watch_id=watch_id))
        finally:
            self._client.unregister_watch_notifications(watch_id)

    async def fuzzy_file_search(
        self,
        query: str,
        roots: list[str],
        *,
        cancellation_token: str | None = None,
    ) -> FuzzyFileSearchResponse:
        """RPC: fuzzyFileSearch."""
        await self._ensure_initialized()
        return await self._client.fuzzy_file_search(
            FuzzyFileSearchParams(query=query, roots=roots, cancellation_token=cancellation_token)
        )


@dataclass(slots=True)
class Thread:
    """Synchronous conversation thread used to run one or more turns."""

    _client: CodexClient
    id: str

    def run(
        self,
        input: RunInput,
        *,
        approval_mode: ApprovalMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        model: str | None = None,
        output_schema: JsonObject | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
        tool_output: TurnToolOutput | None = None,
    ) -> TurnResult:
        """Run a complete turn and collect its final result."""
        turn = self.turn(
            input,
            approval_mode=approval_mode,
            cwd=cwd,
            effort=effort,
            environments=environments,
            model=model,
            output_schema=output_schema,
            personality=personality,
            sandbox=sandbox,
            service_tier=service_tier,
            summary=summary,
            tool_output=tool_output,
        )
        stream = turn.stream()
        try:
            return _collect_turn_result(stream, turn_id=turn.id)
        finally:
            stream.close()

    # BEGIN GENERATED: Thread.flat_methods
    def turn(
        self,
        input: RunInput,
        *,
        approval_mode: ApprovalMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        model: str | None = None,
        output_schema: JsonObject | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
        tool_output: TurnToolOutput | None = None,
    ) -> TurnHandle:
        """Start a turn and return a handle for streaming or control."""
        if environments is not None:
            require_experimental_api(self._client.config, "environments")
        wire_input = _to_wire_input(_normalize_run_input(input))
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = TurnStartParams(
            thread_id=self.id,
            input=wire_input,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            cwd=cwd,
            effort=effort,
            environments=environments,
            model=model,
            output_schema=output_schema,
            personality=personality,
            sandbox_policy=_sandbox_policy(sandbox),
            service_tier=service_tier,
            summary=summary,
            tool_output=tool_output,
        )
        turn = self._client.turn_start(self.id, wire_input, params=params)
        return TurnHandle(self._client, self.id, turn.turn.id)

    # END GENERATED: Thread.flat_methods

    def read(self, *, include_turns: bool = False) -> ThreadReadResponse:
        """Read this thread, optionally including its turn history."""
        return self._client.thread_read(self.id, include_turns=include_turns)

    def set_name(self, name: str) -> ThreadSetNameResponse:
        return self._client.thread_set_name(self.id, name)

    def compact(self) -> ThreadCompactStartResponse:
        return self._client.thread_compact(self.id)

    def unsubscribe(self) -> ThreadUnsubscribeResponse:
        """RPC: thread/unsubscribe."""
        return self._client.thread_unsubscribe(ThreadUnsubscribeParams(thread_id=self.id))

    def turns_list(
        self,
        *,
        cursor: str | None = None,
        items_view: TurnItemsView | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
    ) -> ThreadTurnsListResponse:
        """RPC: thread/turns/list."""
        return self._client.thread_turns_list(
            ThreadTurnsListParams(
                thread_id=self.id,
                cursor=cursor,
                items_view=items_view,
                limit=limit,
                sort_direction=sort_direction,
            )
        )

    def items_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        turn_id: str | None = None,
    ) -> ThreadItemsListResponse:
        """RPC: thread/items/list."""
        return self._client.thread_items_list(
            ThreadItemsListParams(
                thread_id=self.id,
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                turn_id=turn_id,
            )
        )

    def revert(self, before_turn_id: str) -> ThreadRevertResponse:
        """RPC: thread/revert."""
        return self._client.thread_revert(
            ThreadRevertParams(thread_id=self.id, before_turn_id=before_turn_id)
        )

    def inject_items(self, items: list[JsonObject]) -> ThreadInjectItemsResponse:
        """RPC: thread/inject_items."""
        return self._client.thread_inject_items(
            ThreadInjectItemsParams(thread_id=self.id, items=items)
        )

    def metadata_update(
        self,
        *,
        git_info: ThreadMetadataGitInfoUpdateParams | None = None,
        project_id: str | None = None,
    ) -> ThreadMetadataUpdateResponse:
        """RPC: thread/metadata/update."""
        return self._client.thread_metadata_update(
            ThreadMetadataUpdateParams(thread_id=self.id, git_info=git_info, project_id=project_id)
        )

    def section_move(
        self, *, section_id: str | None = None, before_thread_id: str | None = None
    ) -> ThreadSectionMoveResponse:
        """RPC: thread/section/move."""
        return self._client.thread_section_move(
            ThreadSectionMoveParams(
                thread_id=self.id,
                section_id=section_id,
                before_thread_id=before_thread_id,
            )
        )

    def mcp_tool_call(
        self,
        server: str,
        tool: str,
        *,
        arguments: object | None = None,
        field_meta: object | None = None,
    ) -> McpServerToolCallResponse:
        """RPC: mcpServer/tool/call."""
        return self._client.mcp_tool_call(
            McpServerToolCallParams(
                thread_id=self.id,
                server=server,
                tool=tool,
                arguments=arguments,
                field_meta=field_meta,
            )
        )

    def goal_get(self) -> ThreadGoalGetResponse:
        """RPC: thread/goal/get."""
        return self._client.thread_goal_get(ThreadGoalGetParams(thread_id=self.id))

    def goal_set(
        self, *, objective: str | None = None, status: ThreadGoalStatus | None = None
    ) -> ThreadGoalSetResponse:
        """RPC: thread/goal/set."""
        return self._client.thread_goal_set(self.id, objective=objective, status=status)

    def goal_clear(self) -> ThreadGoalClearResponse:
        """RPC: thread/goal/clear."""
        return self._client.thread_goal_clear(self.id)

    def queue_add(self, input: RunInput, *, client_user_message_id: str) -> ThreadQueueAddResponse:
        """RPC: thread/queue/add."""
        require_experimental_api(self._client.config, "thread/queue/add")
        return self._client.thread_queue_add(
            ThreadQueueAddParams(
                thread_id=self.id,
                client_user_message_id=client_user_message_id,
                input=_to_wire_input(_normalize_run_input(input)),
            )
        )

    def queue_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadQueueListResponse:
        """RPC: thread/queue/list."""
        require_experimental_api(self._client.config, "thread/queue/list")
        return self._client.thread_queue_list(
            ThreadQueueListParams(thread_id=self.id, cursor=cursor, limit=limit)
        )

    def queue_update(self, queued_submission_id: str, input: RunInput) -> ThreadQueueUpdateResponse:
        """RPC: thread/queue/update."""
        require_experimental_api(self._client.config, "thread/queue/update")
        return self._client.thread_queue_update(
            ThreadQueueUpdateParams(
                thread_id=self.id,
                queued_submission_id=queued_submission_id,
                input=_to_wire_input(_normalize_run_input(input)),
            )
        )

    def queue_delete(self, queued_submission_id: str) -> ThreadQueueDeleteResponse:
        """RPC: thread/queue/delete."""
        require_experimental_api(self._client.config, "thread/queue/delete")
        return self._client.thread_queue_delete(
            ThreadQueueDeleteParams(thread_id=self.id, queued_submission_id=queued_submission_id)
        )

    def queue_reorder(self, queued_submission_ids: list[str]) -> ThreadQueueReorderResponse:
        """RPC: thread/queue/reorder."""
        require_experimental_api(self._client.config, "thread/queue/reorder")
        return self._client.thread_queue_reorder(
            ThreadQueueReorderParams(thread_id=self.id, queued_submission_ids=queued_submission_ids)
        )

    def queue_start(self, *, queued_submission_id: str | None = None) -> ThreadQueueStartResponse:
        """RPC: thread/queue/start."""
        require_experimental_api(self._client.config, "thread/queue/start")
        return self._client.thread_queue_start(
            ThreadQueueStartParams(thread_id=self.id, queued_submission_id=queued_submission_id)
        )

    def memory_mode_set(self, mode: ThreadMemoryMode) -> ThreadMemoryModeSetResponse:
        """RPC: thread/memoryMode/set."""
        require_experimental_api(self._client.config, "thread/memoryMode/set")
        return self._client.thread_memory_mode_set(
            ThreadMemoryModeSetParams(thread_id=self.id, mode=mode)
        )

    def settings_update(
        self,
        *,
        approval_mode: ApprovalMode | None = None,
        collaboration_mode: CollaborationMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        model: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
    ) -> ThreadSettingsUpdateResponse:
        """RPC: thread/settings/update."""
        require_experimental_api(self._client.config, "thread/settings/update")
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        return self._client.thread_settings_update(
            ThreadSettingsUpdateParams(
                thread_id=self.id,
                approval_policy=approval_policy,
                approvals_reviewer=approvals_reviewer,
                collaboration_mode=collaboration_mode,
                cwd=cwd,
                effort=effort,
                model=model,
                personality=personality,
                sandbox_policy=_sandbox_policy(sandbox),
                service_tier=service_tier,
                summary=summary,
            )
        )


@dataclass(slots=True)
class AsyncThread:
    """Asynchronous conversation thread used to run one or more turns."""

    _codex: AsyncCodex
    id: str

    async def run(
        self,
        input: RunInput,
        *,
        approval_mode: ApprovalMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        model: str | None = None,
        output_schema: JsonObject | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
        tool_output: TurnToolOutput | None = None,
    ) -> TurnResult:
        """Run a complete turn asynchronously and collect its final result."""
        turn = await self.turn(
            input,
            approval_mode=approval_mode,
            cwd=cwd,
            effort=effort,
            environments=environments,
            model=model,
            output_schema=output_schema,
            personality=personality,
            sandbox=sandbox,
            service_tier=service_tier,
            summary=summary,
            tool_output=tool_output,
        )
        stream = turn.stream()
        try:
            return await _collect_async_turn_result(stream, turn_id=turn.id)
        finally:
            await stream.aclose()

    # BEGIN GENERATED: AsyncThread.flat_methods
    async def turn(
        self,
        input: RunInput,
        *,
        approval_mode: ApprovalMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        environments: list[TurnEnvironmentParams] | None = None,
        model: str | None = None,
        output_schema: JsonObject | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
        tool_output: TurnToolOutput | None = None,
    ) -> AsyncTurnHandle:
        """Start a turn and return a handle for streaming or control."""
        if environments is not None:
            require_experimental_api(self._codex._client.config, "environments")
        await self._codex._ensure_initialized()
        wire_input = _to_wire_input(_normalize_run_input(input))
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        params = TurnStartParams(
            thread_id=self.id,
            input=wire_input,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            cwd=cwd,
            effort=effort,
            environments=environments,
            model=model,
            output_schema=output_schema,
            personality=personality,
            sandbox_policy=_sandbox_policy(sandbox),
            service_tier=service_tier,
            summary=summary,
            tool_output=tool_output,
        )
        turn = await self._codex._client.turn_start(
            self.id,
            wire_input,
            params=params,
        )
        return AsyncTurnHandle(self._codex, self.id, turn.turn.id)

    # END GENERATED: AsyncThread.flat_methods

    async def read(self, *, include_turns: bool = False) -> ThreadReadResponse:
        """Read this thread, optionally including its turn history."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_read(self.id, include_turns=include_turns)

    async def set_name(self, name: str) -> ThreadSetNameResponse:
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_set_name(self.id, name)

    async def compact(self) -> ThreadCompactStartResponse:
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_compact(self.id)

    async def unsubscribe(self) -> ThreadUnsubscribeResponse:
        """RPC: thread/unsubscribe."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_unsubscribe(
            ThreadUnsubscribeParams(thread_id=self.id)
        )

    async def turns_list(
        self,
        *,
        cursor: str | None = None,
        items_view: TurnItemsView | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
    ) -> ThreadTurnsListResponse:
        """RPC: thread/turns/list."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_turns_list(
            ThreadTurnsListParams(
                thread_id=self.id,
                cursor=cursor,
                items_view=items_view,
                limit=limit,
                sort_direction=sort_direction,
            )
        )

    async def items_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: SortDirection | None = None,
        turn_id: str | None = None,
    ) -> ThreadItemsListResponse:
        """RPC: thread/items/list."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_items_list(
            ThreadItemsListParams(
                thread_id=self.id,
                cursor=cursor,
                limit=limit,
                sort_direction=sort_direction,
                turn_id=turn_id,
            )
        )

    async def revert(self, before_turn_id: str) -> ThreadRevertResponse:
        """RPC: thread/revert."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_revert(
            ThreadRevertParams(thread_id=self.id, before_turn_id=before_turn_id)
        )

    async def inject_items(self, items: list[JsonObject]) -> ThreadInjectItemsResponse:
        """RPC: thread/inject_items."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_inject_items(
            ThreadInjectItemsParams(thread_id=self.id, items=items)
        )

    async def metadata_update(
        self,
        *,
        git_info: ThreadMetadataGitInfoUpdateParams | None = None,
        project_id: str | None = None,
    ) -> ThreadMetadataUpdateResponse:
        """RPC: thread/metadata/update."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_metadata_update(
            ThreadMetadataUpdateParams(thread_id=self.id, git_info=git_info, project_id=project_id)
        )

    async def section_move(
        self, *, section_id: str | None = None, before_thread_id: str | None = None
    ) -> ThreadSectionMoveResponse:
        """RPC: thread/section/move."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_section_move(
            ThreadSectionMoveParams(
                thread_id=self.id,
                section_id=section_id,
                before_thread_id=before_thread_id,
            )
        )

    async def mcp_tool_call(
        self,
        server: str,
        tool: str,
        *,
        arguments: object | None = None,
        field_meta: object | None = None,
    ) -> McpServerToolCallResponse:
        """RPC: mcpServer/tool/call."""
        await self._codex._ensure_initialized()
        return await self._codex._client.mcp_tool_call(
            McpServerToolCallParams(
                thread_id=self.id,
                server=server,
                tool=tool,
                arguments=arguments,
                field_meta=field_meta,
            )
        )

    async def goal_get(self) -> ThreadGoalGetResponse:
        """RPC: thread/goal/get."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_goal_get(ThreadGoalGetParams(thread_id=self.id))

    async def goal_set(
        self, *, objective: str | None = None, status: ThreadGoalStatus | None = None
    ) -> ThreadGoalSetResponse:
        """RPC: thread/goal/set."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_goal_set(
            self.id, objective=objective, status=status
        )

    async def goal_clear(self) -> ThreadGoalClearResponse:
        """RPC: thread/goal/clear."""
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_goal_clear(self.id)

    async def queue_add(
        self, input: RunInput, *, client_user_message_id: str
    ) -> ThreadQueueAddResponse:
        """RPC: thread/queue/add."""
        require_experimental_api(self._codex._client.config, "thread/queue/add")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_add(
            ThreadQueueAddParams(
                thread_id=self.id,
                client_user_message_id=client_user_message_id,
                input=_to_wire_input(_normalize_run_input(input)),
            )
        )

    async def queue_list(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ThreadQueueListResponse:
        """RPC: thread/queue/list."""
        require_experimental_api(self._codex._client.config, "thread/queue/list")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_list(
            ThreadQueueListParams(thread_id=self.id, cursor=cursor, limit=limit)
        )

    async def queue_update(
        self, queued_submission_id: str, input: RunInput
    ) -> ThreadQueueUpdateResponse:
        """RPC: thread/queue/update."""
        require_experimental_api(self._codex._client.config, "thread/queue/update")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_update(
            ThreadQueueUpdateParams(
                thread_id=self.id,
                queued_submission_id=queued_submission_id,
                input=_to_wire_input(_normalize_run_input(input)),
            )
        )

    async def queue_delete(self, queued_submission_id: str) -> ThreadQueueDeleteResponse:
        """RPC: thread/queue/delete."""
        require_experimental_api(self._codex._client.config, "thread/queue/delete")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_delete(
            ThreadQueueDeleteParams(thread_id=self.id, queued_submission_id=queued_submission_id)
        )

    async def queue_reorder(self, queued_submission_ids: list[str]) -> ThreadQueueReorderResponse:
        """RPC: thread/queue/reorder."""
        require_experimental_api(self._codex._client.config, "thread/queue/reorder")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_reorder(
            ThreadQueueReorderParams(thread_id=self.id, queued_submission_ids=queued_submission_ids)
        )

    async def queue_start(
        self, *, queued_submission_id: str | None = None
    ) -> ThreadQueueStartResponse:
        """RPC: thread/queue/start."""
        require_experimental_api(self._codex._client.config, "thread/queue/start")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_queue_start(
            ThreadQueueStartParams(thread_id=self.id, queued_submission_id=queued_submission_id)
        )

    async def memory_mode_set(self, mode: ThreadMemoryMode) -> ThreadMemoryModeSetResponse:
        """RPC: thread/memoryMode/set."""
        require_experimental_api(self._codex._client.config, "thread/memoryMode/set")
        await self._codex._ensure_initialized()
        return await self._codex._client.thread_memory_mode_set(
            ThreadMemoryModeSetParams(thread_id=self.id, mode=mode)
        )

    async def settings_update(
        self,
        *,
        approval_mode: ApprovalMode | None = None,
        collaboration_mode: CollaborationMode | None = None,
        cwd: str | None = None,
        effort: ReasoningEffort | None = None,
        model: str | None = None,
        personality: Personality | None = None,
        sandbox: Sandbox | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
    ) -> ThreadSettingsUpdateResponse:
        """RPC: thread/settings/update."""
        require_experimental_api(self._codex._client.config, "thread/settings/update")
        await self._codex._ensure_initialized()
        approval_policy, approvals_reviewer = _approval_mode_override_settings(approval_mode)
        return await self._codex._client.thread_settings_update(
            ThreadSettingsUpdateParams(
                thread_id=self.id,
                approval_policy=approval_policy,
                approvals_reviewer=approvals_reviewer,
                collaboration_mode=collaboration_mode,
                cwd=cwd,
                effort=effort,
                model=model,
                personality=personality,
                sandbox_policy=_sandbox_policy(sandbox),
                service_tier=service_tier,
                summary=summary,
            )
        )


@dataclass(slots=True)
class TurnHandle:
    """Control and consume a synchronous turn after it has started."""

    _client: CodexClient
    thread_id: str
    id: str

    def steer(self, input: RunInput) -> TurnSteerResponse:
        """Send additional input to this active turn."""
        return self._client.turn_steer(
            self.thread_id,
            self.id,
            _to_wire_input(_normalize_run_input(input)),
        )

    def interrupt(self) -> TurnInterruptResponse:
        """Request interruption of this active turn."""
        return self._client.turn_interrupt(self.thread_id, self.id)

    def stream(self) -> Iterator[Notification]:
        """Yield only notifications routed to this turn handle."""
        self._client.register_turn_notifications(self.id)
        try:
            while True:
                event = self._client.next_turn_notification(self.id)
                yield event
                if (
                    event.method == "turn/completed"
                    and isinstance(event.payload, TurnCompletedNotification)
                    and event.payload.turn.id == self.id
                ):
                    break
        finally:
            self._client.unregister_turn_notifications(self.id)

    def run(self) -> TurnResult:
        """Consume the turn stream and return its completed result."""
        stream = self.stream()
        try:
            return _collect_turn_result(stream, turn_id=self.id)
        finally:
            stream.close()

    def settings_update(
        self,
        *,
        effort: ReasoningEffort | None = None,
        model: str | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
    ) -> TurnSettingsUpdateResponse:
        """RPC: turn/settings/update."""
        require_experimental_api(self._client.config, "turn/settings/update")
        return self._client.turn_settings_update(
            TurnSettingsUpdateParams(
                thread_id=self.thread_id,
                turn_id=self.id,
                effort=effort,
                model=model,
                service_tier=service_tier,
                summary=summary,
            )
        )


@dataclass(slots=True)
class AsyncTurnHandle:
    """Control and consume an asynchronous turn after it has started."""

    _codex: AsyncCodex
    thread_id: str
    id: str

    async def steer(self, input: RunInput) -> TurnSteerResponse:
        """Send additional input to this active turn."""
        await self._codex._ensure_initialized()
        return await self._codex._client.turn_steer(
            self.thread_id,
            self.id,
            _to_wire_input(_normalize_run_input(input)),
        )

    async def interrupt(self) -> TurnInterruptResponse:
        """Request interruption of this active turn."""
        await self._codex._ensure_initialized()
        return await self._codex._client.turn_interrupt(self.thread_id, self.id)

    async def stream(self) -> AsyncIterator[Notification]:
        """Yield only notifications routed to this async turn handle."""
        await self._codex._ensure_initialized()
        self._codex._client.register_turn_notifications(self.id)
        try:
            while True:
                event = await self._codex._client.next_turn_notification(self.id)
                yield event
                if (
                    event.method == "turn/completed"
                    and isinstance(event.payload, TurnCompletedNotification)
                    and event.payload.turn.id == self.id
                ):
                    break
        finally:
            self._codex._client.unregister_turn_notifications(self.id)

    async def run(self) -> TurnResult:
        """Consume the turn stream and return its completed result."""
        stream = self.stream()
        try:
            return await _collect_async_turn_result(stream, turn_id=self.id)
        finally:
            await stream.aclose()

    async def settings_update(
        self,
        *,
        effort: ReasoningEffort | None = None,
        model: str | None = None,
        service_tier: str | None = None,
        summary: ReasoningSummary | None = None,
    ) -> TurnSettingsUpdateResponse:
        """RPC: turn/settings/update."""
        require_experimental_api(self._codex._client.config, "turn/settings/update")
        await self._codex._ensure_initialized()
        return await self._codex._client.turn_settings_update(
            TurnSettingsUpdateParams(
                thread_id=self.thread_id,
                turn_id=self.id,
                effort=effort,
                model=model,
                service_tier=service_tier,
                summary=summary,
            )
        )
