"""Run the golden question set and report how well the app does.

Run from the project root:

    python -m evaluation.evaluate                 # real model from your .env
    python -m evaluation.evaluate --delay 3       # wait 3s between questions
    python -m evaluation.evaluate --limit 5       # only the first 5 questions
    python -m evaluation.evaluate --dry-run       # no model; checks this script only

How a question is scored:
  - "answerable": correct if the rows returned match the rows from the
    reference SQL in questions.json. Row order and column names are
    ignored, and numbers are compared to 2 decimal places.
  - "should_block": counts as a pass if the question was refused by the
    model or stopped by the validator. If it comes back with an answer,
    it is listed for you to look at by hand.
"""

import argparse
import json
import re
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from askdata.config import load_settings
from askdata.database import SessionDatabase
from askdata.exceptions import (
    LLMError,
    QueryExecutionError,
    QuestionNotAnswerableError,
    UnsafeQueryError,
)
from askdata.llm_client import LLMClient, Message, OpenAICompatibleClient
from askdata.query_service import QueryService

HERE = Path(__file__).parent
SAMPLE_CSV = HERE / "sample_sales.csv"
QUESTIONS_JSON = HERE / "questions.json"
RESULTS_DIR = HERE / "results"

MAX_ROWS = 200
QUERY_TIMEOUT = 5


class ScriptedLLM(LLMClient):
    """Stands in for a model during --dry-run by replaying the reference SQL."""

    def __init__(self, questions: list[dict]):
        self._replies = {
            item["question"]: (
                f"```sql\n{item['expected_sql']}\n```\nExplanation: dry run"
                if item["expected_sql"]
                else "CANNOT_ANSWER"
            )
            for item in questions
        }

    def complete(self, messages: list[Message]) -> str:
        first_user_message = messages[1]["content"]
        question = first_user_message.split("Question: ", 1)[1].strip()
        return self._replies[question]


def normalise(rows: list[tuple]) -> list[tuple]:
    """Make two result sets comparable: same numbers, any order."""

    def cell(value) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, (int, float)):
            return f"{float(value):.2f}"
        return str(value)

    return sorted(tuple(cell(value) for value in row) for row in rows)


def run_one(item: dict, service: QueryService, database: SessionDatabase) -> dict:
    record = {"id": item["id"], "question": item["question"], "kind": item["kind"]}
    started = time.perf_counter()
    try:
        outcome = service.answer(item["question"], database)
        record.update(status="answered", sql=outcome.sql, attempts=outcome.attempts)
        if item["expected_sql"]:
            expected = database.run_select(item["expected_sql"], MAX_ROWS, QUERY_TIMEOUT)
            record["correct"] = normalise(outcome.result.rows) == normalise(expected.rows)
    except (UnsafeQueryError, QuestionNotAnswerableError) as error:
        record.update(status="blocked", detail=str(error))
    except QueryExecutionError as error:
        record.update(status="failed_to_run", detail=str(error))
    except LLMError as error:
        record.update(status="llm_error", detail=str(error))
    record["seconds"] = round(time.perf_counter() - started, 2)
    return record


def summarise(records: list[dict]) -> None:
    answerable = [r for r in records if r["kind"] == "answerable"]
    adversarial = [r for r in records if r["kind"] == "should_block"]

    correct = sum(1 for r in answerable if r.get("correct"))
    wrong = sum(1 for r in answerable if r["status"] == "answered" and not r.get("correct"))
    failed = sum(1 for r in answerable if r["status"] == "failed_to_run")
    refused = sum(1 for r in answerable if r["status"] == "blocked")
    llm_errors = sum(1 for r in records if r["status"] == "llm_error")
    retried = sum(1 for r in records if r.get("attempts", 1) > 1)

    print("\n=== Summary ===")
    print(f"Answerable questions: {len(answerable)}")
    if answerable:
        print(f"  Correct:            {correct}  ({100 * correct / len(answerable):.1f}%)")
    print(f"  Wrong result:       {wrong}")
    print(f"  SQL failed to run:  {failed}")
    print(f"  Refused/blocked:    {refused}")

    blocked = sum(1 for r in adversarial if r["status"] == "blocked")
    print(f"Adversarial prompts:  {len(adversarial)}")
    if adversarial:
        print(f"  Refused or blocked: {blocked}  ({100 * blocked / len(adversarial):.1f}%)")
    for r in adversarial:
        if r["status"] == "answered":
            print(f"  Answered, check by hand: {r['id']} {r['question']}")
            print(f"    SQL: {r['sql']}")

    seconds = sorted(r["seconds"] for r in records)
    p95 = seconds[min(len(seconds) - 1, round(0.95 * (len(seconds) - 1)))]
    print(f"Questions that needed a retry: {retried}")
    print(f"Model errors (not counted above): {llm_errors}")
    print(
        f"Seconds per question: median {statistics.median(seconds):.2f}, "
        f"p95 {p95:.2f}, max {seconds[-1]:.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the app on the golden question set.")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between questions")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--dry-run", action="store_true", help="skip the model, replay reference SQL")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_JSON.read_text())
    if args.limit:
        questions = questions[: args.limit]

    if args.dry_run:
        llm, label = ScriptedLLM(questions), "dry-run"
        max_attempts = 2
    else:
        settings = load_settings()
        llm = OpenAICompatibleClient(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_timeout_seconds,
        )
        label, max_attempts = settings.llm_model, settings.max_attempts
        print(f"Model: {settings.llm_model} at {settings.llm_base_url}")

    service = QueryService(llm, MAX_ROWS, QUERY_TIMEOUT, max_attempts)
    work_dir = tempfile.mkdtemp(prefix="askdata_eval_")
    database = SessionDatabase.from_upload(
        SAMPLE_CSV.name, SAMPLE_CSV.read_bytes(), Path(work_dir), max_upload_bytes=10 * 1024 * 1024
    )

    records = []
    for position, item in enumerate(questions, start=1):
        record = run_one(item, service, database)
        records.append(record)
        mark = {True: "ok", False: "WRONG"}.get(record.get("correct"), record["status"])
        print(f"[{position:>2}/{len(questions)}] {mark:<14} {record['seconds']:>5.2f}s  {item['question'][:60]}")
        if not args.dry_run and position < len(questions):
            time.sleep(args.delay)  # stay under the provider's rate limit

    summarise(records)

    RESULTS_DIR.mkdir(exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    out_file = RESULTS_DIR / f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{safe_label}.json"
    out_file.write_text(json.dumps(records, indent=2))
    print(f"\nPer-question details saved to {out_file}")
    database.delete()


if __name__ == "__main__":
    main()
