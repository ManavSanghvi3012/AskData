import pytest

from askdata.exceptions import UnsafeQueryError
from askdata.sql_validator import SqlValidator


@pytest.fixture
def validator():
    return SqlValidator(allowed_table="sales")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        "select region, count(*) from sales group by region having count(*) > 1",
        "SELECT * FROM sales;",  # a single trailing semicolon is fine
        "SELECT created_at FROM sales",  # the word 'create' in a column name
        "SELECT strftime('%Y-%m', order_date), SUM(amount) FROM sales GROUP BY 1",
        "SELECT s.region FROM sales AS s JOIN sales AS t ON s.order_id = t.order_id",
        "WITH monthly AS (SELECT region FROM sales) SELECT * FROM monthly",
        "SELECT region FROM sales UNION SELECT region FROM sales",
        "SELECT * FROM (SELECT region FROM sales) AS sub",
        "SELECT region FROM SALES",  # table names are not case sensitive
    ],
)
def test_safe_queries_are_accepted(validator, sql):
    assert validator.validate(sql).upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize(
    "sql, message",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("DROP TABLE sales", "Only SELECT"),
        ("DELETE FROM sales", "Only SELECT"),
        ("UPDATE sales SET amount = 0", "Only SELECT"),
        ("INSERT INTO sales VALUES (1)", "Only SELECT"),
        ("ALTER TABLE sales ADD COLUMN x", "Only SELECT"),
        ("PRAGMA table_info(sales)", "Only SELECT"),
        ("ATTACH DATABASE 'x.db' AS x", "Only SELECT"),
        ("SELECT 1; DROP TABLE sales", "Exactly one"),
        ("SELECT * FROM users", "not available"),
        ("SELECT * FROM sqlite_master", "not available"),
        ("SELECT * FROM main.sales", "Schema-qualified"),
        ("SELECT * FROM pragma_table_info('sales')", "not available"),
        ("SELECT * FROM sales, users", "not available"),
        ("SELECT * FROM sales WHERE id IN (SELECT id FROM users)", "not available"),
        ("SELECT load_extension('evil')", "not allowed"),
        ("SELECT * FROM (", "not valid SQL"),
    ],
)
def test_unsafe_queries_are_rejected(validator, sql, message):
    with pytest.raises(UnsafeQueryError, match=message):
        validator.validate(sql)


def test_delete_hidden_behind_a_with_clause_is_rejected(validator):
    with pytest.raises(UnsafeQueryError):
        validator.validate("WITH x AS (SELECT 1) DELETE FROM sales")


def test_error_messages_have_no_terminal_colour_codes(validator):
    with pytest.raises(UnsafeQueryError) as caught:
        validator.validate("SELECT * FROM (")
    assert "\x1b" not in str(caught.value)


def test_returned_sql_comes_from_the_checked_tree(validator):
    # Comments are dropped, so nothing unchecked can ride along in the text.
    cleaned = validator.validate("SELECT region FROM sales -- x */ ; DROP TABLE sales; /*")
    assert cleaned == "SELECT region FROM sales"
