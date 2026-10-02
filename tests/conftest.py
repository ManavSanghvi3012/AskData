import pandas as pd
import pytest

from askdata.database import SessionDatabase

SALES_CSV = (
    "order_id,order_date,region,amount,customer_email,notes\n"
    "1,2024-01-05,North,100.5,ann@example.com,first order\n"
    "2,2024-01-20,South,50,bob@example.com,\n"
    "3,2024-02-11,North,75.25,ann@example.com,repeat customer\n"
    "4,2024-02-15,East,20,cy@example.com,\n"
)


@pytest.fixture
def sales_database(tmp_path) -> SessionDatabase:
    """A small real database, built through the same path the app uses."""
    return SessionDatabase.from_upload(
        "sales.csv", SALES_CSV.encode(), tmp_path, max_upload_bytes=1_000_000
    )


@pytest.fixture
def messy_frame() -> pd.DataFrame:
    return pd.DataFrame({"Order ID": [1, 2], "Order Date": ["2024-01-05", "2024-02-10"]})
