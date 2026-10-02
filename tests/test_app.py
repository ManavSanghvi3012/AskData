"""Smoke test: the page starts and handles the 'nothing uploaded yet' state."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP_FILE = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture(autouse=True)
def fresh_cache():
    # build_service() is cached; without this, one test's settings leak into the next.
    st.cache_resource.clear()


def test_page_loads_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_API_KEY", "test_key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-oss-120b")
    app = AppTest.from_file(APP_FILE).run()
    assert not app.exception
    assert app.title[0].value == "AskData"


def test_missing_settings_show_a_helpful_error(monkeypatch):
    from askdata import config

    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    app = AppTest.from_file(APP_FILE).run()
    assert not app.exception
    assert "LLM_BASE_URL is not set" in app.error[0].value
