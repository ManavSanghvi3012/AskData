"""Decide whether a piece of SQL is safe to run.

Rules, in plain words:
  1. It must parse as SQL, and be exactly one statement.
  2. That statement must be a SELECT (a UNION of SELECTs is fine).
  3. It may only read the uploaded table (or its own WITH-clause names).
  4. A few dangerous SQLite functions are blocked.

SQL is parsed into a syntax tree instead of being checked through keyword
matching. Keyword matching can reject valid column names and miss equivalent
SQL forms. The syntax tree identifies the actual statement structure.

validate() returns SQL regenerated from the checked tree. So what runs is
exactly what was checked, not the raw text the model wrote.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from askdata.exceptions import UnsafeQueryError

BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile"}

_ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


class SqlValidator:
    def __init__(self, allowed_table: str):
        self._allowed_table = allowed_table.lower()

    def validate(self, sql: str) -> str:
        statement = self._parse_single_statement(sql)
        self._check_statement_type(statement)
        self._check_tables(statement)
        self._check_functions(statement)
        # comments=False drops any comment text, so nothing odd can ride
        # along inside a comment in the SQL we hand to SQLite.
        return statement.sql(dialect="sqlite", comments=False)

    def _parse_single_statement(self, sql: str) -> exp.Expression:
        if not sql or not sql.strip():
            raise UnsafeQueryError("The query is empty.")
        try:
            parsed = sqlglot.parse(sql, read="sqlite")
        except SqlglotError as exc:
            raise UnsafeQueryError(f"The query is not valid SQL: {_short(exc)}") from exc

        # parse() returns None for blank statements, such as a trailing ";".
        statements = [item for item in parsed if item is not None]
        if len(statements) != 1:
            raise UnsafeQueryError("Exactly one SQL statement is allowed.")
        return statements[0]

    def _check_statement_type(self, statement: exp.Expression) -> None:
        if not isinstance(statement, (exp.Select, exp.Union)):
            raise UnsafeQueryError("Only SELECT queries are allowed.")

    def _check_tables(self, statement: exp.Expression) -> None:
        # Names defined by the query itself, e.g. WITH monthly AS (...)
        own_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            name = table.name.lower()
            if table.db or table.catalog:
                raise UnsafeQueryError("Schema-qualified table names are not allowed.")
            if name != self._allowed_table and name not in own_names:
                shown = table.sql(dialect="sqlite")
                raise UnsafeQueryError(
                    f"'{shown}' is not available. Only the table "
                    f"'{self._allowed_table}' can be queried."
                )

    def _check_functions(self, statement: exp.Expression) -> None:
        # Functions sqlglot does not know about show up as Anonymous nodes.
        for function in statement.find_all(exp.Anonymous):
            if str(function.name).lower() in BLOCKED_FUNCTIONS:
                raise UnsafeQueryError(f"The function '{function.name}' is not allowed.")


def _short(error: Exception) -> str:
    """sqlglot errors contain terminal colour codes and several lines."""
    first_line = _ANSI_CODES.sub("", str(error)).strip().splitlines()[0]
    return first_line[:200]
