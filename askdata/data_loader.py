"""Turn an uploaded CSV/XLSX file into a clean pandas DataFrame.

"Clean" here means: readable file, tidy column names, and dates stored as
plain text (YYYY-MM-DD) because that is what SQLite's date functions expect.
"""

import io
import re
from pathlib import Path

import pandas as pd

from askdata.exceptions import DataLoadError

ALLOWED_SUFFIXES = (".csv", ".xlsx")
MAX_COLUMNS = 80

# A text column is only treated as a date if its NAME suggests it. Guessing
# from values alone goes wrong (a column of month names like "May" would
# happily parse as dates).
DATE_NAME_HINTS = ("date", "time", "_at")


def load_dataframe(file_name: str, file_bytes: bytes, max_bytes: int) -> pd.DataFrame:
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DataLoadError("Only .csv and .xlsx files are supported.")
    if len(file_bytes) > max_bytes:
        raise DataLoadError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")

    try:
        if suffix == ".csv":
            df = _read_csv(file_bytes)
        else:
            # The application reads the first worksheet only.
            df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:  # pandas/openpyxl raise many different types
        raise DataLoadError(f"Could not read the file: {exc}") from exc

    if df.empty or len(df.columns) == 0:
        raise DataLoadError("The file has no data rows.")
    if len(df.columns) > MAX_COLUMNS:
        raise DataLoadError(f"The file has more than {MAX_COLUMNS} columns.")

    df.columns = clean_column_names(df.columns)
    return normalise_dates(df)


def _read_csv(file_bytes: bytes) -> pd.DataFrame:
    try:
        # utf-8-sig quietly drops the invisible marker Excel adds to CSVs.
        return pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig")
    except UnicodeDecodeError:
        # Older exports are often Latin-1, which can decode any byte.
        return pd.read_csv(io.BytesIO(file_bytes), encoding="latin-1")


def _slug(text: str) -> str:
    """Create a lowercase SQL identifier using underscores."""
    return re.sub(r"[^0-9a-z]+", "_", str(text).strip().lower()).strip("_")


def clean_column_names(columns) -> list[str]:
    used: set[str] = set()
    cleaned: list[str] = []
    for position, raw in enumerate(columns, start=1):
        name = _slug(raw) or f"column_{position}"
        if name[0].isdigit():
            name = f"col_{name}"
        base, counter = name, 2
        while name in used:  # two columns can clean down to the same name
            name = f"{base}_{counter}"
            counter += 1
        used.add(name)
        cleaned.append(name)
    return cleaned


def make_table_name(file_name: str) -> str:
    name = _slug(Path(file_name).stem) or "data"
    return f"t_{name}" if name[0].isdigit() else name


def normalise_dates(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            df[column] = _to_iso_text(series)
        elif _is_text(series) and any(hint in column for hint in DATE_NAME_HINTS):
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            # Only convert when every non-empty value parsed. A half-parsed
            # column would silently lose data.
            if parsed.notna().sum() == series.notna().sum():
                df[column] = _to_iso_text(parsed)
    return df


def _is_text(series: pd.Series) -> bool:
    return series.dtype == object or pd.api.types.is_string_dtype(series)


def _to_iso_text(series: pd.Series) -> pd.Series:
    non_empty = series.dropna()
    has_time = bool((non_empty.dt.normalize() != non_empty).any())
    return series.dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")
