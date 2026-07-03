from __future__ import annotations

import importlib
import math
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import procrastinate
from loguru import logger
from procrastinate import RetryDecision
from procrastinate.jobs import Job
from pydantic import BaseModel, Field

from open_notebook.database.repository import get_database_url, parse_record_ids, repo_query

COMMAND_APP = "open_notebook"
COMMAND_ID_PREFIX = "command:"

# The Procrastinate CLI imports this module from the installed package context,
# where the repo root is not always on sys.path. The task modules live in the
# top-level commands/ package, so make that path explicit before import_paths run.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COMMAND_MODULES = (
    "commands.embedding_commands",
    "commands.source_commands",
    "commands.podcast_commands",
    "commands.example_commands",
)

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_database_url()),
    import_paths=COMMAND_MODULES,
)


class ExecutionContext(BaseModel):
    command_id: str


class CommandInput(BaseModel):
    execution_context: Optional[ExecutionContext] = Field(default=None, exclude=True)


class CommandOutput(BaseModel):
    pass


@dataclass
class CommandStatus:
    status: str
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created: Optional[Any] = None
    updated: Optional[Any] = None
    progress: Optional[dict[str, Any]] = None


class StopOnRetryStrategy(procrastinate.BaseRetryStrategy):
    def __init__(
        self,
        *,
        max_attempts: int,
        wait_min: int = 1,
        wait_max: int = 60,
        stop_on: Iterable[type[Exception]] = (),
    ) -> None:
        self.max_attempts = max_attempts
        self.wait_min = wait_min
        self.wait_max = wait_max
        self.stop_on = tuple(stop_on)

    def get_retry_decision(
        self, *, exception: BaseException, job: Job
    ) -> RetryDecision | None:
        if self.stop_on and isinstance(exception, self.stop_on):
            return None
        if job.attempts >= self.max_attempts:
            return None

        wait_seconds = min(
            self.wait_max,
            max(self.wait_min, int(math.pow(2, max(job.attempts, 0)))),
        )
        return RetryDecision(retry_in={"seconds": wait_seconds})


def retry_strategy(
    *,
    max_attempts: int,
    wait_min: int = 1,
    wait_max: int = 60,
    stop_on: Iterable[type[Exception]] = (),
) -> StopOnRetryStrategy:
    return StopOnRetryStrategy(
        max_attempts=max_attempts,
        wait_min=wait_min,
        wait_max=wait_max,
        stop_on=stop_on,
    )


def task_name(app_name: str, command_name: str) -> str:
    return f"{app_name}.{command_name}"


def format_command_id(job_id: int | str) -> str:
    return f"{COMMAND_ID_PREFIX}{job_id}"


def parse_command_id(command_id: str | int) -> int:
    value = str(command_id)
    if value.startswith(COMMAND_ID_PREFIX):
        value = value[len(COMMAND_ID_PREFIX) :]
    return int(value)


def execution_context_for_job(job_id: int | str) -> ExecutionContext:
    return ExecutionContext(command_id=format_command_id(job_id))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if key != "execution_context"
        }
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return parse_record_ids(value)


def _normalize_command_args(command_args: dict[str, Any] | BaseModel) -> dict[str, Any]:
    normalized = _jsonable(command_args)
    if not isinstance(normalized, dict):
        raise TypeError("Command arguments must be a mapping")
    normalized.pop("execution_context", None)
    return normalized


def import_command_modules() -> None:
    for module_name in COMMAND_MODULES:
        importlib.import_module(module_name)


@asynccontextmanager
async def _opened_app():
    if getattr(app.connector, "_async_pool", None) is not None:
        yield app
    else:
        async with app.open_async():
            yield app


async def _upsert_command_record(
    *,
    command_id: str,
    app_id: str,
    name: str,
    status: str,
    input_data: Optional[dict[str, Any]] = None,
    result: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
    progress: Optional[dict[str, Any]] = None,
) -> None:
    try:
        await repo_query(
            """
            INSERT INTO command (
                id, app_id, name, status, input, result, error_message, progress, updated
            )
            VALUES (
                $id, $app_id, $name, $status, $input, $result, $error_message, $progress, now()
            )
            ON CONFLICT (id) DO UPDATE SET
                app_id = EXCLUDED.app_id,
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                input = COALESCE(EXCLUDED.input, command.input),
                result = EXCLUDED.result,
                error_message = EXCLUDED.error_message,
                progress = EXCLUDED.progress,
                updated = now()
            """,
            {
                "id": command_id,
                "app_id": app_id,
                "name": name,
                "status": status,
                "input": input_data or {},
                "result": result,
                "error_message": error_message,
                "progress": progress,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to update command mirror row {command_id}: {e}")


async def submit_command(
    app_name: str,
    command_name: str,
    command_args: dict[str, Any] | BaseModel,
) -> str:
    args = _normalize_command_args(command_args)
    full_task_name = task_name(app_name, command_name)

    async with _opened_app() as opened:
        job_id = await opened.configure_task(
            full_task_name, allow_unknown=False
        ).defer_async(**args)

    command_id = format_command_id(job_id)
    await _upsert_command_record(
        command_id=command_id,
        app_id=app_name,
        name=command_name,
        status="queued",
        input_data=args,
    )
    logger.info(f"Submitted command job {command_id} for {full_task_name}")
    return command_id


async def mark_command_running(
    *,
    command_id: str,
    app_id: str,
    name: str,
    input_data: dict[str, Any],
) -> None:
    await _upsert_command_record(
        command_id=command_id,
        app_id=app_id,
        name=name,
        status="running",
        input_data=input_data,
    )


async def mark_command_completed(
    *,
    command_id: str,
    app_id: str,
    name: str,
    result: Optional[dict[str, Any]],
) -> None:
    await _upsert_command_record(
        command_id=command_id,
        app_id=app_id,
        name=name,
        status="completed",
        result=result,
    )


async def mark_command_failed(
    *,
    command_id: str,
    app_id: str,
    name: str,
    error_message: str,
) -> None:
    await _upsert_command_record(
        command_id=command_id,
        app_id=app_id,
        name=name,
        status="failed",
        result={"error_message": error_message},
        error_message=error_message,
    )


def _public_status(status: Optional[str]) -> str:
    mapping = {
        "todo": "queued",
        "doing": "running",
        "succeeded": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "aborting": "running",
        "aborted": "failed",
    }
    return mapping.get(str(status), str(status) if status else "unknown")


def _storage_status(public_status: Optional[str]) -> Optional[str]:
    mapping = {
        "queued": "todo",
        "running": "doing",
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "aborted": "aborted",
    }
    return mapping.get(public_status or "")


async def get_command_status(command_id: str | int) -> Optional[CommandStatus]:
    job_id = parse_command_id(command_id)
    public_command_id = format_command_id(job_id)

    rows = await repo_query(
        """
        SELECT
            pj.id,
            pj.status::text AS job_status,
            pj.task_name,
            pj.args,
            c.result,
            c.error_message,
            c.progress,
            COALESCE(c.created, min(e.at)) AS created,
            COALESCE(c.updated, max(e.at)) AS updated
        FROM procrastinate_jobs pj
        LEFT JOIN command c ON c.id = $command_id
        LEFT JOIN procrastinate_events e ON e.job_id = pj.id
        WHERE pj.id = $job_id
        GROUP BY pj.id, pj.status, pj.task_name, pj.args, c.id, c.result,
                 c.error_message, c.progress, c.created, c.updated
        """,
        {"job_id": job_id, "command_id": public_command_id},
    )
    if rows:
        row = rows[0]
        return CommandStatus(
            status=_public_status(row.get("job_status")),
            result=row.get("result"),
            error_message=row.get("error_message"),
            created=row.get("created"),
            updated=row.get("updated"),
            progress=row.get("progress"),
        )

    mirror_rows = await repo_query(
        "SELECT * FROM command WHERE id = $command_id",
        {"command_id": public_command_id},
    )
    if mirror_rows:
        row = mirror_rows[0]
        return CommandStatus(
            status=row.get("status") or "unknown",
            result=row.get("result"),
            error_message=row.get("error_message"),
            created=row.get("created"),
            updated=row.get("updated"),
            progress=row.get("progress"),
        )
    return None


async def list_command_jobs(
    *,
    command_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters = []
    params: dict[str, Any] = {"limit": limit}

    if command_filter:
        filters.append("pj.task_name = $task_name")
        params["task_name"] = (
            command_filter
            if "." in command_filter
            else task_name(COMMAND_APP, command_filter)
        )
    if status_filter:
        storage_status = _storage_status(status_filter) or status_filter
        filters.append("pj.status = $status::procrastinate_job_status")
        params["status"] = storage_status

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = await repo_query(
        f"""
        SELECT
            pj.id,
            pj.status::text AS job_status,
            pj.task_name,
            pj.args,
            c.result,
            c.error_message,
            c.progress,
            COALESCE(c.created, min(e.at)) AS created,
            COALESCE(c.updated, max(e.at)) AS updated
        FROM procrastinate_jobs pj
        LEFT JOIN command c ON c.id = ('command:' || pj.id::text)
        LEFT JOIN procrastinate_events e ON e.job_id = pj.id
        {where_sql}
        GROUP BY pj.id, pj.status, pj.task_name, pj.args, c.id, c.result,
                 c.error_message, c.progress, c.created, c.updated
        ORDER BY pj.id DESC
        LIMIT $limit
        """,
        params,
    )

    jobs: list[dict[str, Any]] = []
    for row in rows:
        command_id = format_command_id(row["id"])
        jobs.append(
            {
                "job_id": command_id,
                "command_id": command_id,
                "status": _public_status(row.get("job_status")),
                "task_name": row.get("task_name"),
                "input": row.get("args"),
                "result": row.get("result"),
                "error_message": row.get("error_message"),
                "created": str(row["created"]) if row.get("created") else None,
                "updated": str(row["updated"]) if row.get("updated") else None,
                "progress": row.get("progress"),
            }
        )
    return jobs


async def cancel_command_job(command_id: str | int) -> bool:
    job_id = parse_command_id(command_id)
    async with _opened_app() as opened:
        cancelled = await opened.job_manager.cancel_job_by_id_async(job_id)
    if cancelled:
        await _upsert_command_record(
            command_id=format_command_id(job_id),
            app_id=COMMAND_APP,
            name="unknown",
            status="cancelled",
        )
    return cancelled


def registered_commands() -> list[dict[str, str]]:
    import_command_modules()
    app.perform_import_paths()
    items: list[dict[str, str]] = []
    for full_name in sorted(app.tasks):
        if not full_name.startswith(f"{COMMAND_APP}."):
            continue
        command = full_name.split(".", 1)[1]
        items.append(
            {
                "app_id": COMMAND_APP,
                "name": command,
                "full_id": full_name,
            }
        )
    return items


async def run_task_handler(
    *,
    context: procrastinate.JobContext,
    command_name: str,
    input_model: type[CommandInput],
    handler: Any,
    task_kwargs: dict[str, Any],
) -> dict[str, Any]:
    command_id = format_command_id(context.job.id or "unknown")
    input_data = input_model(
        **task_kwargs,
        execution_context=execution_context_for_job(context.job.id or "unknown"),
    )

    await mark_command_running(
        command_id=command_id,
        app_id=COMMAND_APP,
        name=command_name,
        input_data=_normalize_command_args(task_kwargs),
    )
    try:
        result = await handler(input_data)
    except Exception as e:
        await mark_command_failed(
            command_id=command_id,
            app_id=COMMAND_APP,
            name=command_name,
            error_message=str(e),
        )
        raise

    result_data = _jsonable(result)
    await mark_command_completed(
        command_id=command_id,
        app_id=COMMAND_APP,
        name=command_name,
        result=result_data if isinstance(result_data, dict) else {"result": result_data},
    )
    return result_data if isinstance(result_data, dict) else {"result": result_data}
