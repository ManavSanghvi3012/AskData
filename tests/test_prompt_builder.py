import pytest

from askdata.prompt_builder import (
    add_retry_messages,
    build_messages,
    mask_pii,
    parse_reply,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("write to ann.lee+x@example.co.uk now", "write to <email> now"),
        ("ssn 123-45-6789", "ssn <id>"),
        ("call 555-123-4567", "call <phone>"),
        ("card 4111111111111111", "card <number>"),
        ("2024-03-15 10:20:30", "2024-03-15 10:20:30"),  # dates survive
        ("order 1001, qty 5", "order 1001, qty 5"),  # short numbers survive
    ],
)
def test_mask_pii(text, expected):
    assert mask_pii(text) == expected


def test_prompt_contains_schema_values_and_masked_samples(sales_database):
    messages = build_messages(
        "How many orders?",
        sales_database.table_name,
        sales_database.columns,
        sales_database.preview,
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    prompt = messages[1]["content"]
    assert "Table: sales" in prompt
    assert "- amount (REAL)" in prompt
    assert "values: East, North, South" in prompt
    assert "Question: How many orders?" in prompt
    assert "ann@example.com" not in prompt  # masked before leaving the machine
    assert "<email>" in prompt


def test_only_three_sample_rows_are_sent(sales_database):
    messages = build_messages("q", "sales", sales_database.columns, sales_database.preview)
    sample_block = messages[1]["content"].split("Sample rows:\n")[1].split("\n\nQuestion")[0]
    assert len(sample_block.splitlines()) == 1 + 3  # header + 3 rows


def test_retry_messages_keep_history_and_add_the_error():
    first = [{"role": "user", "content": "hi"}]
    more = add_retry_messages(first, "bad reply", "no such column: x")
    assert more[:1] == first
    assert more[1] == {"role": "assistant", "content": "bad reply"}
    assert "no such column: x" in more[2]["content"]
    assert len(first) == 1  # the original list is not changed


def test_parse_reply_with_fence_and_explanation():
    reply = "```sql\nSELECT 1\n```\nExplanation: Returns one."
    assert parse_reply(reply) == ("SELECT 1", "Returns one.")


def test_parse_reply_without_fence():
    assert parse_reply("SELECT 2\nExplanation: Two.") == ("SELECT 2", "Two.")


def test_parse_reply_without_explanation():
    assert parse_reply("```\nSELECT 3\n```") == ("SELECT 3", "")
