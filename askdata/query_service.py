"""Coordinate prompt creation, model calls, SQL validation, and execution.

Invalid generated SQL can be returned to the model for another attempt. The
default configuration allows one repair attempt.
"""

from dataclasses import dataclass

from askdata.database import QueryResult, SessionDatabase
from askdata.exceptions import (
    AskDataError,
    QueryExecutionError,
    QuestionNotAnswerableError,
    UnsafeQueryError,
)
from askdata.llm_client import LLMClient
from askdata.prompt_builder import (
    CANNOT_ANSWER,
    add_retry_messages,
    build_messages,
    parse_reply,
)
from askdata.sql_validator import SqlValidator


@dataclass(frozen=True)
class QueryOutcome:
    sql: str  # the exact SQL that ran
    explanation: str  # the model's own one-line description of that SQL
    result: QueryResult
    attempts: int  # number of model attempts used


class QueryService:
    def __init__(
        self,
        llm: LLMClient,
        max_result_rows: int,
        query_timeout_seconds: float,
        max_attempts: int = 2,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._llm = llm
        self._max_result_rows = max_result_rows
        self._query_timeout_seconds = query_timeout_seconds
        self._max_attempts = max_attempts

    def answer(self, question: str, database: SessionDatabase) -> QueryOutcome:
        if not question.strip():
            raise AskDataError("Please type a question first.")

        validator = SqlValidator(allowed_table=database.table_name)
        messages = build_messages(
            question, database.table_name, database.columns, database.preview
        )

        for attempt in range(1, self._max_attempts + 1):
            reply = self._llm.complete(messages)

            if reply.strip().upper().startswith(CANNOT_ANSWER):
                raise QuestionNotAnswerableError(
                    "This question cannot be answered from the uploaded table."
                )

            sql, explanation = parse_reply(reply)
            try:
                safe_sql = validator.validate(sql)
                result = database.run_select(
                    safe_sql, self._max_result_rows, self._query_timeout_seconds
                )
            except (UnsafeQueryError, QueryExecutionError) as error:
                if attempt == self._max_attempts:
                    raise  # out of tries, let the caller show the error
                messages = add_retry_messages(messages, reply, str(error))
                continue

            return QueryOutcome(safe_sql, explanation, result, attempt)
