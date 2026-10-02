import pytest

from askdata.exceptions import (
    AskDataError,
    LLMError,
    QueryExecutionError,
    QuestionNotAnswerableError,
    UnsafeQueryError,
)
from askdata.llm_client import LLMClient
from askdata.query_service import QueryService
from tests.fakes import FakeLLM


def sql_reply(sql, explanation="Explains it."):
    return f"```sql\n{sql}\n```\nExplanation: {explanation}"


def make_service(replies, max_attempts=2):
    llm = FakeLLM(replies)
    return QueryService(llm, 100, 5, max_attempts), llm


def test_happy_path(sales_database):
    service, llm = make_service([sql_reply("SELECT COUNT(*) FROM sales", "Counts orders.")])
    outcome = service.answer("How many orders?", sales_database)
    assert outcome.result.rows == [(4,)]
    assert outcome.explanation == "Counts orders."
    assert outcome.attempts == 1
    assert len(llm.calls) == 1


def test_a_failing_query_is_retried_with_the_error_message(sales_database):
    service, llm = make_service(
        [sql_reply("SELECT nope FROM sales"), sql_reply("SELECT COUNT(*) FROM sales")]
    )
    outcome = service.answer("How many orders?", sales_database)
    assert outcome.attempts == 2
    retry_prompt = llm.calls[1][-1]["content"]
    assert "no such column" in retry_prompt


def test_unsafe_sql_is_blocked_after_the_last_attempt(sales_database):
    service, llm = make_service([sql_reply("DROP TABLE sales")] * 2)
    with pytest.raises(UnsafeQueryError, match="Only SELECT"):
        service.answer("Drop the table", sales_database)
    assert len(llm.calls) == 2
    # and the data is untouched
    assert sales_database.run_select("SELECT COUNT(*) FROM sales", 10, 5).rows == [(4,)]


def test_other_tables_are_blocked(sales_database):
    service, _ = make_service([sql_reply("SELECT * FROM sqlite_master")] * 2)
    with pytest.raises(UnsafeQueryError, match="not available"):
        service.answer("Show internals", sales_database)


def test_model_can_refuse(sales_database):
    service, llm = make_service(["CANNOT_ANSWER"])
    with pytest.raises(QuestionNotAnswerableError):
        service.answer("What is the weather?", sales_database)
    assert len(llm.calls) == 1  # a refusal is final, no retry


def test_single_attempt_setting_means_no_retry(sales_database):
    service, llm = make_service([sql_reply("SELECT nope FROM sales")], max_attempts=1)
    with pytest.raises(QueryExecutionError):
        service.answer("q", sales_database)
    assert len(llm.calls) == 1


def test_empty_question_never_reaches_the_model(sales_database):
    service, llm = make_service([])
    with pytest.raises(AskDataError, match="type a question"):
        service.answer("   ", sales_database)
    assert llm.calls == []


def test_model_errors_pass_through(sales_database):
    class DownLLM(LLMClient):
        def complete(self, messages):
            raise LLMError("provider down")

    service = QueryService(DownLLM(), 100, 5)
    with pytest.raises(LLMError, match="provider down"):
        service.answer("q", sales_database)


def test_max_attempts_must_be_positive():
    with pytest.raises(ValueError):
        QueryService(FakeLLM([]), 100, 5, max_attempts=0)
