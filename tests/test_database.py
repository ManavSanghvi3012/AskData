import pytest

from askdata.exceptions import DataLoadError, QueryExecutionError


def test_table_name_row_count_and_types(sales_database):
    assert sales_database.table_name == "sales"
    assert sales_database.row_count == 4
    types = {column.name: column.sql_type for column in sales_database.columns}
    assert types["order_id"] == "INTEGER"
    assert types["amount"] == "REAL"
    assert types["order_date"] == "TEXT"


def test_low_cardinality_text_columns_list_their_values(sales_database):
    region = next(c for c in sales_database.columns if c.name == "region")
    assert region.example_values == ("East", "North", "South")


def test_preview_is_returned_with_null_for_blank_cells(sales_database):
    assert sales_database.preview.columns[0] == "order_id"
    assert len(sales_database.preview.rows) == 4
    assert sales_database.preview.rows[1][-1] is None  # blank notes cell


def test_run_select_returns_rows(sales_database):
    result = sales_database.run_select(
        "SELECT region, SUM(amount) FROM sales GROUP BY region ORDER BY region", 100, 5
    )
    assert result.columns == ["region", "SUM(amount)"]
    assert result.rows == [("East", 20.0), ("North", 175.75), ("South", 50.0)]
    assert result.truncated is False


def test_results_are_cut_at_the_row_limit(sales_database):
    result = sales_database.run_select("SELECT * FROM sales", 2, 5)
    assert len(result.rows) == 2
    assert result.truncated is True


def test_connection_is_read_only(sales_database):
    with pytest.raises(QueryExecutionError, match="readonly"):
        sales_database.run_select("DELETE FROM sales", 10, 5)


def test_runaway_query_is_stopped(sales_database):
    endless = (
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
        "SELECT COUNT(*) FROM r"
    )
    with pytest.raises(QueryExecutionError, match="took longer"):
        sales_database.run_select(endless, 10, timeout_seconds=0.5)


def test_sql_errors_become_query_execution_errors(sales_database):
    with pytest.raises(QueryExecutionError, match="no such column"):
        sales_database.run_select("SELECT nope FROM sales", 10, 5)


def test_each_upload_gets_its_own_file(tmp_path):
    from askdata.database import SessionDatabase

    first = SessionDatabase.from_upload("a.csv", b"x\n1\n", tmp_path, 1000)
    second = SessionDatabase.from_upload("a.csv", b"x\n2\n", tmp_path, 1000)
    assert first.db_path != second.db_path
    assert first.run_select("SELECT x FROM a", 10, 5).rows == [(1,)]
    assert second.run_select("SELECT x FROM a", 10, 5).rows == [(2,)]


def test_bad_upload_raises_before_any_file_is_made(tmp_path):
    from askdata.database import SessionDatabase

    with pytest.raises(DataLoadError):
        SessionDatabase.from_upload("a.txt", b"x", tmp_path, 1000)
    assert list(tmp_path.iterdir()) == []


def test_delete_removes_the_file(sales_database):
    sales_database.delete()
    assert not sales_database.db_path.exists()
