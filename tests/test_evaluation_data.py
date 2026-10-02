"""Guards the golden question set so a bad edit cannot go unnoticed."""

import json
from pathlib import Path

import pytest

from askdata.database import SessionDatabase
from askdata.sql_validator import SqlValidator

EVALUATION = Path(__file__).parent.parent / "evaluation"
QUESTIONS = json.loads((EVALUATION / "questions.json").read_text())


@pytest.fixture(scope="module")
def sample_database(tmp_path_factory):
    csv_path = EVALUATION / "sample_sales.csv"
    return SessionDatabase.from_upload(
        csv_path.name, csv_path.read_bytes(), tmp_path_factory.mktemp("eval"), 10_000_000
    )


def test_ids_are_unique_and_kinds_are_known():
    ids = [item["id"] for item in QUESTIONS]
    assert len(ids) == len(set(ids))
    assert {item["kind"] for item in QUESTIONS} == {"answerable", "should_block"}


@pytest.mark.parametrize("item", [q for q in QUESTIONS if q["kind"] == "answerable"], ids=lambda q: q["id"])
def test_reference_sql_passes_the_validator_and_returns_rows(item, sample_database):
    safe_sql = SqlValidator(sample_database.table_name).validate(item["expected_sql"])
    original = sample_database.run_select(item["expected_sql"], 200, 5)
    checked = sample_database.run_select(safe_sql, 200, 5)
    assert original.rows, "reference SQL should return something"
    assert original.rows == checked.rows  # regenerating the SQL changed nothing
