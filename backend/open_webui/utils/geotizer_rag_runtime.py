"""Runtime execution and shadow tracing for GeoMAS RetrievalPlan objects.

The active arm returns only traces produced by the typed retrieval gateway.
The shadow arm runs the same callable in background tasks and persists its
result without exposing it to the GeoTeaser evidence or user response.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from open_webui.utils.geotizer_retrieval import (
    RetrievalPlan,
    build_grounded_retrieval_trace,
    normalize_retrieval_traces,
)

PlanQueryCall = Callable[
    [Mapping[str, Any], Sequence[str]],
    Awaitable[Mapping[str, Any]],
]

SHADOW_RECORD_SCHEMA = 'geomas.rag_shadow_dispatch.v1'
_COLLECTION_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$')
_BACKGROUND_TASKS: set[asyncio.Task] = set()
log = logging.getLogger(__name__)


def _consume_background_result(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        log.error('GeoMAS RAG shadow dispatch failed: %s', type(error).__name__)


def _env_bool(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name, 'False')).strip().casefold() == 'true'


def _bounded_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(str(environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


def _unique_nonempty(values: Sequence[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def parse_collection_names(raw: Any) -> tuple[str, ...]:
    """Parse a JSON array or comma-separated collection allowlist."""

    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        values = list(raw)
    else:
        text = str(raw or '').strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            values = text.split(',')
        else:
            values = parsed if isinstance(parsed, list) else []
    collections = _unique_nonempty(values)
    return tuple(
        value
        for value in collections
        if _COLLECTION_PATTERN.fullmatch(value)
    )


@dataclass(frozen=True)
class GeoMASRAGRuntimeSettings:
    """Fail-safe settings for the mutually exclusive active/shadow arms."""

    active_enabled: bool
    shadow_enabled: bool
    collections: tuple[str, ...]
    index_version: str
    timeout_ms: int
    max_concurrency: int
    trace_dir: Path

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        data_dir: str | Path,
    ) -> GeoMASRAGRuntimeSettings:
        environ = os.environ if environ is None else environ
        trace_dir = str(environ.get('GEOMAS_RAG_SHADOW_TRACE_DIR', '')).strip()
        return cls(
            active_enabled=_env_bool(environ, 'ENABLE_GEOMAS_RAG_V2'),
            shadow_enabled=_env_bool(environ, 'ENABLE_GEOMAS_RAG_V2_SHADOW'),
            collections=parse_collection_names(
                environ.get('GEOMAS_RAG_V2_COLLECTIONS', '')
            ),
            index_version=str(
                environ.get('GEOMAS_RAG_V2_INDEX_VERSION', '')
            ).strip(),
            timeout_ms=_bounded_int(
                environ,
                'GEOMAS_RAG_QUERY_TIMEOUT_MS',
                30_000,
                minimum=100,
                maximum=120_000,
            ),
            max_concurrency=_bounded_int(
                environ,
                'GEOMAS_RAG_QUERY_MAX_CONCURRENCY',
                3,
                minimum=1,
                maximum=8,
            ),
            trace_dir=(
                Path(trace_dir)
                if trace_dir
                else Path(data_dir) / 'geomas_rag_shadow'
            ),
        )

    @property
    def mode(self) -> Literal['disabled', 'shadow', 'active', 'invalid']:
        if self.active_enabled and self.shadow_enabled:
            return 'invalid'
        if self.active_enabled:
            return 'active'
        if self.shadow_enabled:
            return 'shadow'
        return 'disabled'

    def configuration_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.active_enabled and self.shadow_enabled:
            errors.append(
                'ENABLE_GEOMAS_RAG_V2 and ENABLE_GEOMAS_RAG_V2_SHADOW '
                'are mutually exclusive'
            )
        if self.mode in {'active', 'shadow'} and not self.collections:
            errors.append('GEOMAS_RAG_V2_COLLECTIONS is required')
        if self.mode in {'active', 'shadow'} and not self.index_version:
            errors.append('GEOMAS_RAG_V2_INDEX_VERSION is required')
        return tuple(errors)


@dataclass(frozen=True)
class RetrievalDispatch:
    plan: RetrievalPlan
    trace: Mapping[str, Any]
    latency_ms: float
    status: Literal['completed', 'timed_out', 'failed']


def _failure_trace(
    plan: RetrievalPlan,
    collections: Sequence[str],
    error_type: str,
) -> dict[str, Any]:
    return build_grounded_retrieval_trace(
        plan.as_dict(),
        None,
        collections=collections,
        backend_path=[],
        backend_failures=[
            {
                'backend': 'geomas_plan_gateway',
                'error_type': error_type,
                'terminal': True,
            }
        ],
    )


async def execute_retrieval_plans(
    plans: Sequence[RetrievalPlan],
    query_call: PlanQueryCall,
    *,
    collections: Sequence[str],
    timeout_ms: int,
    max_concurrency: int,
) -> tuple[RetrievalDispatch, ...]:
    """Execute planned queries with bounded concurrency and typed failures."""

    executable = tuple(plan for plan in plans if plan.status == 'planned')
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def execute(plan: RetrievalPlan) -> RetrievalDispatch:
        started = time.perf_counter()
        status: Literal['completed', 'timed_out', 'failed'] = 'completed'
        async with semaphore:
            try:
                raw = await asyncio.wait_for(
                    query_call(plan.as_dict(), collections),
                    timeout=max(0.1, timeout_ms / 1000),
                )
                normalized = normalize_retrieval_traces([raw], [plan])
                if len(normalized) != 1:
                    raise ValueError('typed gateway returned an invalid trace')
                trace: Mapping[str, Any] = normalized[0]
            except asyncio.TimeoutError:  # noqa: UP041 - Python 3.10 compatibility
                status = 'timed_out'
                trace = _failure_trace(plan, collections, 'TimeoutError')
            except Exception as error:
                status = 'failed'
                trace = _failure_trace(
                    plan,
                    collections,
                    type(error).__name__,
                )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return RetrievalDispatch(
            plan=plan,
            trace=trace,
            latency_ms=latency_ms,
            status=status,
        )

    return tuple(await asyncio.gather(*(execute(plan) for plan in executable)))


def _safe_run_dir(run_id: str) -> str:
    readable = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(run_id)).strip('.-')
    readable = readable[:48] or 'run'
    digest = hashlib.sha256(str(run_id).encode('utf-8')).hexdigest()[:12]
    return f'{readable}-{digest}'


class ShadowTraceStore:
    """Append-only JSONL store for shadow-only records."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = asyncio.Lock()

    def path_for(self, run_id: str) -> Path:
        return self.root / _safe_run_dir(run_id) / 'retrieval_trace.jsonl'

    async def append(self, run_id: str, records: Sequence[Mapping[str, Any]]) -> Path:
        path = self.path_for(run_id)
        lines = [
            json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n'
            for record in records
        ]
        async with self._lock:
            await asyncio.to_thread(self._append_sync, path, lines)
        return path

    @staticmethod
    def _append_sync(path: Path, lines: Sequence[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.writelines(lines)
            stream.flush()
            os.fsync(stream.fileno())


class GeoMASRAGDispatcher:
    """Execute the active arm or submit an isolated background shadow arm."""

    def __init__(
        self,
        settings: GeoMASRAGRuntimeSettings,
        query_call: PlanQueryCall,
        *,
        trace_store: ShadowTraceStore | None = None,
    ):
        self.settings = settings
        self.query_call = query_call
        self.trace_store = trace_store or ShadowTraceStore(settings.trace_dir)

    async def execute_active(
        self,
        plans: Sequence[RetrievalPlan],
    ) -> tuple[dict[str, Any], ...]:
        """Fail closed to typed no-hit/failure traces, never to legacy RAG."""

        if self.settings.mode != 'active':
            raise RuntimeError('GeoMAS RAG v2 active dispatcher is disabled')
        errors = self.settings.configuration_errors()
        if errors:
            raise RuntimeError('; '.join(errors))
        dispatched = await execute_retrieval_plans(
            plans,
            self.query_call,
            collections=self.settings.collections,
            timeout_ms=self.settings.timeout_ms,
            max_concurrency=self.settings.max_concurrency,
        )
        return tuple(dict(item.trace) for item in dispatched)

    def submit_shadow(
        self,
        plans: Sequence[RetrievalPlan],
        *,
        run_id: str,
        object_name: str,
        batch_id: str,
    ) -> asyncio.Task | None:
        """Start v2 without awaiting it or changing the v1 result path."""

        if self.settings.mode != 'shadow':
            return None
        task = asyncio.create_task(
            self._execute_and_persist_shadow(
                plans,
                run_id=run_id,
                object_name=object_name,
                batch_id=batch_id,
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_consume_background_result)
        return task

    async def _execute_and_persist_shadow(
        self,
        plans: Sequence[RetrievalPlan],
        *,
        run_id: str,
        object_name: str,
        batch_id: str,
    ) -> None:
        errors = self.settings.configuration_errors()
        if errors:
            records = [
                {
                    'schema': SHADOW_RECORD_SCHEMA,
                    'recorded_at': dt.datetime.now(
                        dt.timezone.utc  # noqa: UP017 - Python 3.10 compatibility
                    ).isoformat(),
                    'arm': 'geomas_rag_v2_shadow',
                    'run_id': run_id,
                    'object_name': object_name,
                    'batch_id': batch_id,
                    'status': 'configuration_error',
                    'latency_ms': 0.0,
                    'deadline_ms': self.settings.timeout_ms,
                    'user_visible': False,
                    'errors': list(errors),
                    'trace': None,
                }
            ]
        else:
            dispatched = await execute_retrieval_plans(
                plans,
                self.query_call,
                collections=self.settings.collections,
                timeout_ms=self.settings.timeout_ms,
                max_concurrency=self.settings.max_concurrency,
            )
            recorded_at = dt.datetime.now(
                dt.timezone.utc  # noqa: UP017 - Python 3.10 compatibility
            ).isoformat()
            records = [
                {
                    'schema': SHADOW_RECORD_SCHEMA,
                    'recorded_at': recorded_at,
                    'arm': 'geomas_rag_v2_shadow',
                    'run_id': run_id,
                    'object_name': object_name,
                    'batch_id': batch_id,
                    'plan_id': item.plan.plan_id,
                    'query_id': item.plan.query_id,
                    'status': item.status,
                    'latency_ms': item.latency_ms,
                    'deadline_ms': self.settings.timeout_ms,
                    'user_visible': False,
                    'trace': dict(item.trace),
                }
                for item in dispatched
            ]
        await self.trace_store.append(run_id, records)


async def drain_background_dispatches(
    *,
    timeout_seconds: float | None = None,
) -> None:
    """Wait for currently scheduled shadow writes (tests and graceful shutdown)."""

    pending = tuple(_BACKGROUND_TASKS)
    if not pending:
        return
    if timeout_seconds is None:
        await asyncio.gather(*pending, return_exceptions=True)
        return
    _, unfinished = await asyncio.wait(
        pending,
        timeout=max(0.0, timeout_seconds),
    )
    for task in unfinished:
        task.cancel()
    if unfinished:
        await asyncio.gather(*unfinished, return_exceptions=True)
