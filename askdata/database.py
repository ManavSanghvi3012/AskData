"""Store each upload in a separate temporary SQLite database.

Queries use a read only connection with a time limit. This provides a second
safety layer after SQL validation because SQLite rejects write operations.
"""

import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from askdata.data_loader import load_dataframe, make_table_name
from askdata.exceptions import QueryExecutionError

PREVIEW_ROWS = 5
MAX_EXAMPLE_VALUES = 8  # list a text column's values only if it has few
MAX_EXAMPLE_LENGTH = 40  # ...and they are short (not free-text notes)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    sql_type: str  # INTEGER, REAL or TEXT
    # For text columns with only a few repeated values (like region or
    # status). Showing the model the exact spellings avoids queries such
    # as WHERE region = 'north' when the data says 'North'.
    example_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True when there were more rows than we kept


class SessionDatabase:
    def __init__(
        self,
        db_path: Path,
        table_name: str,
        columns: list[ColumnInfo],
        row_count: int,
        preview: QueryResult,
    ):
        self.db_path = db_path
        self.table_name = table_name
        self.columns = columns
        self.row_count = row_count
        self.preview = preview

    @classmethod
    def from_upload(
        cls, file_name: str, file_bytes: bytes, work_dir: Path, max_upload_bytes: int
    ) -> "SessionDatabase":
        df = load_dataframe(file_name, file_bytes, max_upload_bytes)
        table_name = make_table_name(file_name)
        columns = [_describe_column(df[name]) for name in df.columns]

        db_path = Path(work_dir) / f"{uuid.uuid4().hex}.sqlite"
        with closing(sqlite3.connect(db_path)) as connection:
            df.to_sql(
                table_name,
                connection,
                index=False,
                dtype={column.name: column.sql_type for column in columns},
            )

        preview = _run_read_only(
            db_path, f'SELECT * FROM "{table_name}"', PREVIEW_ROWS, timeout_seconds=5
        )
        return cls(db_path, table_name, columns, len(df), preview)

    def run_select(self, sql: str, max_rows: int, timeout_seconds: float) -> QueryResult:
        return _run_read_only(self.db_path, sql, max_rows, timeout_seconds)

    def delete(self) -> None:
        self.db_path.unlink(missing_ok=True)


def _describe_column(series: pd.Series) -> ColumnInfo:
    sql_type = _sqlite_type(series)
    examples: tuple[str, ...] = ()
    if sql_type == "TEXT":
        values = series.dropna().astype(str)
        distinct = values.unique()
        looks_categorical = (
            0 < len(distinct) <= MAX_EXAMPLE_VALUES
            and len(distinct) < len(values)  # at least some repeats
            and all(len(value) <= MAX_EXAMPLE_LENGTH for value in distinct)
        )
        if looks_categorical:
            examples = tuple(sorted(distinct))
    return ColumnInfo(name=str(series.name), sql_type=sql_type, example_values=examples)


def _sqlite_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "REAL"
    return "TEXT"


def _run_read_only(
    db_path: Path, sql: str, max_rows: int, timeout_seconds: float
) -> QueryResult:
    # mode=ro makes SQLite itself reject any write attempt.
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    deadline = time.monotonic() + timeout_seconds
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            # SQLite calls this every 10,000 steps. Returning 1 aborts the
            # query, which is how we stop runaway queries.
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0, 10_000
            )
            cursor = connection.execute(sql)
            columns = [item[0] for item in cursor.description or []]
            # Fetch one extra row so we can tell whether we cut the result.
            fetched = cursor.fetchmany(max_rows + 1)
    except sqlite3.Error as exc:
        if "interrupted" in str(exc).lower():
            raise QueryExecutionError(
                f"The query took longer than {timeout_seconds:g} seconds and was stopped."
            ) from exc
        raise QueryExecutionError(str(exc)) from exc

    return QueryResult(
        columns=columns,
        rows=[tuple(row) for row in fetched[:max_rows]],
        truncated=len(fetched) > max_rows,
    )
