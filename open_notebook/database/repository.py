import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar, Union

from loguru import logger
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

try:
    from pgvector.psycopg import register_vector_async
except Exception:  # pragma: no cover - pgvector may be unavailable in partial envs
    register_vector_async = None

T = TypeVar("T", Dict[str, Any], List[Dict[str, Any]])

NAMED_PARAM_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")
JSONB_COLUMNS = {
    "asset",
    "topics",
    "modalities",
    "config",
    "credentials",
    "input",
    "speaker_profile",
    "episode_profile",
    "speakers",
    "transcript",
    "outline",
    "result",
    "progress",
}


class RecordID(str):
    """String-compatible record id shim preserving the old table:id shape."""

    @classmethod
    def parse(cls, value: Union[str, "RecordID"]) -> "RecordID":
        return value if isinstance(value, cls) else cls(str(value))


def get_database_url() -> str:
    """Get the Postgres connection URL."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://open_notebook:open_notebook@localhost:5432/open_notebook",
    )


def parse_record_ids(obj: Any) -> Any:
    """Recursively convert RecordID values into strings."""
    if isinstance(obj, dict):
        return {k: parse_record_ids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [parse_record_ids(item) for item in obj]
    if isinstance(obj, RecordID):
        return str(obj)
    return obj


def ensure_record_id(value: Union[str, RecordID]) -> RecordID:
    """Ensure a value uses the legacy table:id record-id string form."""
    if isinstance(value, RecordID):
        return value
    return RecordID.parse(value)


def split_record_id(record_id: Union[str, RecordID]) -> tuple[str, str]:
    value = str(record_id)
    if ":" not in value:
        raise ValueError(f"Record id must use table:id form: {value}")
    table, local_id = value.split(":", 1)
    return table, local_id


@asynccontextmanager
async def db_connection():
    conn = await AsyncConnection.connect(get_database_url(), row_factory=dict_row)
    try:
        if register_vector_async is not None:
            try:
                await register_vector_async(conn)
            except Exception:
                # First boot creates the extension in migration 001, so the type may
                # not exist yet when the migration table is initialized.
                pass
        yield conn
    finally:
        await conn.close()


def _normalize_query(query_str: str) -> str:
    query = query_str.strip()
    if query.upper() == "RETURN 1":
        return "SELECT 1 AS value"
    if query.endswith(";"):
        query = query[:-1]
    for table in ("source_embedding", "source_insight", "reference", "artifact"):
        prefix = f"DELETE {table} "
        if query.upper().startswith(prefix.upper()):
            return f"DELETE FROM {table} {query[len(prefix):]}"
    return query


def _convert_params(query: str) -> str:
    return NAMED_PARAM_RE.sub(r"%(\1)s", query)


def _coerce_param(value: Any) -> Any:
    if isinstance(value, RecordID):
        return str(value)
    if isinstance(value, dict):
        return Jsonb({k: _coerce_param(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_coerce_param(v) for v in value]
    return value


def _coerce_data_value(key: str, value: Any) -> Any:
    if isinstance(value, RecordID):
        return str(value)
    if key in JSONB_COLUMNS and value is not None:
        return Jsonb(parse_record_ids(value))
    if isinstance(value, datetime):
        return value
    return value


async def _select_record(record_id: Union[str, RecordID]) -> List[Dict[str, Any]]:
    table, _ = split_record_id(record_id)
    query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(sql.Identifier(table))
    async with db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (str(record_id),))
            rows = await cur.fetchall()
            return parse_record_ids(rows)


async def repo_query(
    query_str: str, vars: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Execute a parameterized SQL query and return rows as dictionaries."""
    vars = vars or {}
    query = _normalize_query(query_str)

    compact = " ".join(query.split()).lower()
    if compact in {"select * from $id", "select * from only $id"} and "id" in vars:
        return await _select_record(vars["id"])
    if compact in {
        "select * from $record_id",
        "select * from only $record_id",
    } and "record_id" in vars:
        return await _select_record(vars["record_id"])

    sql_query = _convert_params(query)
    params = {key: _coerce_param(value) for key, value in vars.items()}

    async with db_connection() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql_query, params)
                if cur.description:
                    rows = await cur.fetchall()
                    return parse_record_ids(rows)
                await conn.commit()
                return []
        except Exception as e:
            await conn.rollback()
            logger.exception(e)
            raise


async def repo_create(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new record in the specified table."""
    data = dict(data)
    data.pop("id", None)
    now = datetime.now(timezone.utc)
    data.setdefault("created", now)
    data.setdefault("updated", now)
    data["id"] = f"{table}:{uuid.uuid4().hex}"

    columns = list(data.keys())
    values = [_coerce_data_value(key, data[key]) for key in columns]

    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )

    try:
        async with db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, values)
                row = await cur.fetchone()
                await conn.commit()
                if not row:
                    raise RuntimeError("Insert returned no row")
                return parse_record_ids(row)
    except Exception as e:
        logger.exception(e)
        raise RuntimeError("Failed to create record")


async def repo_relate(
    source: str, relationship: str, target: str, data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Create a relationship row between two record ids."""
    existing = await repo_query(
        f"SELECT * FROM {relationship} WHERE in_id = $source AND out_id = $target",
        {"source": str(source), "target": str(target)},
    )
    if existing:
        return existing

    data = dict(data or {})
    data.update(
        {
            "id": f"{relationship}:{uuid.uuid4().hex}",
            "in_id": str(source),
            "out_id": str(target),
            "created": datetime.now(timezone.utc),
            "updated": datetime.now(timezone.utc),
        }
    )
    created = await repo_create(relationship, data)
    return [created]


async def repo_upsert(
    table: str, id: Optional[str], data: Dict[str, Any], add_timestamp: bool = False
) -> List[Dict[str, Any]]:
    """Create or update a record in the specified table."""
    data = dict(data)
    data.pop("id", None)
    record_id = str(id) if id else f"{table}:{uuid.uuid4().hex}"
    if add_timestamp:
        data["updated"] = datetime.now(timezone.utc)

    exists = await _select_record(record_id)
    if exists:
        return await repo_update(table, record_id, data)

    data["id"] = record_id
    now = datetime.now(timezone.utc)
    data.setdefault("created", now)
    data.setdefault("updated", now)

    columns = list(data.keys())
    values = [_coerce_data_value(key, data[key]) for key in columns]
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    async with db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, values)
            row = await cur.fetchone()
            await conn.commit()
            return [parse_record_ids(row)] if row else []


async def repo_update(
    table: str, id: str, data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Update an existing record by table and id."""
    record_id = str(id) if ":" in str(id) else f"{table}:{id}"
    data = dict(data)
    data.pop("id", None)
    data["updated"] = datetime.now(timezone.utc)

    if not data:
        return await _select_record(record_id)

    assignments = [
        sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder())
        for key in data.keys()
    ]
    values = [_coerce_data_value(key, data[key]) for key in data.keys()]
    values.append(record_id)

    query = sql.SQL("UPDATE {} SET {} WHERE id = %s RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(assignments),
    )

    try:
        async with db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, values)
                rows = await cur.fetchall()
                await conn.commit()
                return parse_record_ids(rows)
    except Exception as e:
        logger.exception(e)
        raise RuntimeError(f"Failed to update record: {str(e)}")


async def repo_delete(record_id: Union[str, RecordID]):
    """Delete a record by record id."""
    table, _ = split_record_id(record_id)
    query = sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table))
    try:
        async with db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (str(record_id),))
                await conn.commit()
                return cur.rowcount > 0
    except Exception as e:
        logger.exception(e)
        raise RuntimeError(f"Failed to delete record: {str(e)}")


async def repo_insert(
    table: str, data: List[Dict[str, Any]], ignore_duplicates: bool = False
) -> List[Dict[str, Any]]:
    """Bulk create records in the specified table."""
    created = []
    for row in data:
        try:
            created.append(await repo_create(table, row))
        except Exception:
            if not ignore_duplicates:
                raise
    return created
