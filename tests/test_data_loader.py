import io

import pandas as pd
import pytest

from askdata.data_loader import (
    clean_column_names,
    load_dataframe,
    make_table_name,
    normalise_dates,
)
from askdata.exceptions import DataLoadError

BIG = 1_000_000


def test_clean_column_names_makes_safe_unique_names():
    names = clean_column_names(["Order ID", "order-id", "2024 Sales", "", "Total ($)"])
    assert names == ["order_id", "order_id_2", "col_2024_sales", "column_4", "total"]


@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("Sales 2024.csv", "sales_2024"),
        ("2024 sales.csv", "t_2024_sales"),
        ("***.csv", "data"),
    ],
)
def test_make_table_name(file_name, expected):
    assert make_table_name(file_name) == expected


def test_loads_csv_and_cleans_headers():
    df = load_dataframe("a.csv", b"Order ID,Total ($)\n1,5\n2,7\n", BIG)
    assert list(df.columns) == ["order_id", "total"]
    assert len(df) == 2


def test_loads_xlsx():
    buffer = io.BytesIO()
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(buffer, index=False)
    df = load_dataframe("book.xlsx", buffer.getvalue(), BIG)
    assert df["b"].tolist() == ["x", "y"]


def test_latin1_csv_is_still_readable():
    df = load_dataframe("a.csv", "name\ncaf\xe9\n".encode("latin-1"), BIG)
    assert df["name"].tolist() == ["caf\xe9"]


@pytest.mark.parametrize(
    "file_name, content, message",
    [
        ("notes.txt", b"hello", "Only .csv and .xlsx"),
        ("big.csv", b"a\n1\n" * 10, "larger than"),
        ("empty.csv", b"a,b\n", "no data rows"),
        ("broken.xlsx", b"this is not an excel file", "Could not read"),
    ],
)
def test_bad_files_give_clear_errors(file_name, content, message):
    max_bytes = 10 if file_name == "big.csv" else BIG
    with pytest.raises(DataLoadError, match=message):
        load_dataframe(file_name, content, max_bytes)


def test_date_named_text_columns_become_iso_dates(messy_frame):
    messy_frame["Order Date"] = ["01/05/2024", "02/10/2024"]
    messy_frame.columns = ["order_id", "order_date"]
    result = normalise_dates(messy_frame)
    assert result["order_date"].tolist() == ["2024-01-05", "2024-02-10"]


def test_text_column_with_a_non_date_is_left_alone():
    df = pd.DataFrame({"start_date": ["2024-01-05", "not a date"]})
    assert normalise_dates(df)["start_date"].tolist() == ["2024-01-05", "not a date"]


def test_columns_without_a_date_hint_are_not_converted():
    df = pd.DataFrame({"month": ["May", "June"]})
    assert normalise_dates(df)["month"].tolist() == ["May", "June"]
