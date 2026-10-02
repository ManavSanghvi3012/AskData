"""Streamlit front end. Run with:  streamlit run app.py

This file only draws the page and calls into the askdata package. The real
work (loading, prompting, validating, running) lives there so it can be
tested without a browser.
"""

import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from askdata.config import Settings, load_settings
from askdata.database import SessionDatabase
from askdata.exceptions import AskDataError, ConfigError
from askdata.llm_client import OpenAICompatibleClient
from askdata.query_service import QueryService

st.set_page_config(page_title="AskData", layout="wide")


@st.cache_resource
def build_service() -> tuple[Settings, QueryService]:
    """Read settings and create the model client once, not on every click."""
    settings = load_settings()
    llm = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_timeout_seconds,
    )
    service = QueryService(
        llm,
        settings.max_result_rows,
        settings.query_timeout_seconds,
        settings.max_attempts,
    )
    return settings, service


def load_upload(uploaded_file, settings: Settings) -> SessionDatabase | None:
    """Build a database for a newly uploaded file; reuse it on later reruns."""
    state = st.session_state
    if state.get("upload_id") == uploaded_file.file_id:
        return state.get("database")

    # A different file than last time: drop the old database and answer.
    if state.get("database"):
        state["database"].delete()
    state["upload_id"] = uploaded_file.file_id
    state["database"] = None
    state["last_answer"] = None

    work_dir = state.setdefault("work_dir", tempfile.mkdtemp(prefix="askdata_"))
    try:
        state["database"] = SessionDatabase.from_upload(
            uploaded_file.name,
            uploaded_file.getvalue(),
            Path(work_dir),
            settings.max_upload_bytes,
        )
    except AskDataError as error:
        st.error(str(error))
    return state["database"]


def show_data_summary(database: SessionDatabase) -> None:
    st.success(f"Loaded {database.row_count:,} rows into table '{database.table_name}'.")
    left, right = st.columns([1, 2])
    with left:
        st.caption("Columns")
        st.dataframe(
            pd.DataFrame(
                [{"column": c.name, "type": c.sql_type} for c in database.columns]
            ),
            hide_index=True,
        )
    with right:
        st.caption("First rows")
        st.dataframe(
            pd.DataFrame(database.preview.rows, columns=database.preview.columns),
            hide_index=True,
        )


def show_answer(question: str, outcome) -> None:
    st.subheader("Answer")
    st.caption(f"Question: {question}")
    result = outcome.result
    if result.rows:
        st.dataframe(pd.DataFrame(result.rows, columns=result.columns), hide_index=True)
    else:
        st.info("The query ran but returned no rows.")
    if result.truncated:
        st.warning(f"Only the first {len(result.rows)} rows are shown.")
    if outcome.explanation:
        st.write(outcome.explanation)
    if outcome.attempts > 1:
        st.caption(f"The model needed {outcome.attempts} attempts to produce a valid query.")
    with st.expander("SQL that was run"):
        st.code(outcome.sql, language="sql")


def main() -> None:
    st.title("AskData")
    st.write("Upload a spreadsheet and ask questions about it in plain English.")

    try:
        settings, service = build_service()
    except ConfigError as error:
        st.error(str(error))
        st.stop()

    with st.sidebar:
        st.write(f"Model: {settings.llm_model}")
        st.write(f"Provider: {urlparse(settings.llm_base_url).netloc}")
        st.caption(
            "The model receives column names, selected example values and "
            "up to three sample rows. Common emails and long numbers are masked."
        )

    uploaded_file = st.file_uploader("Upload a CSV or XLSX file", type=["csv", "xlsx"])
    if uploaded_file is None:
        st.info("Upload a file to get started. evaluation/sample_sales.csv works as an example.")
        st.stop()

    database = load_upload(uploaded_file, settings)
    if database is None:
        st.stop()
    show_data_summary(database)

    with st.form("ask_form"):
        question = st.text_input("Your question", placeholder="Which region had the most orders?")
        submitted = st.form_submit_button("Ask")

    if submitted:
        try:
            with st.spinner("Thinking..."):
                outcome = service.answer(question, database)
            st.session_state["last_answer"] = (question, outcome)
        except AskDataError as error:
            st.session_state["last_answer"] = None
            st.error(str(error))

    if st.session_state.get("last_answer"):
        show_answer(*st.session_state["last_answer"])


main()
