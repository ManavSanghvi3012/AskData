import pytest

from askdata import config
from askdata.exceptions import ConfigError


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    # Stop a developer's real .env from leaking into these tests.
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "MAX_RESULT_ROWS"):
        monkeypatch.delenv(name, raising=False)


def set_required(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "some-model")


def test_loads_values_and_defaults(monkeypatch):
    set_required(monkeypatch)
    settings = config.load_settings()
    assert settings.llm_model == "some-model"
    assert settings.max_result_rows == 200
    assert settings.max_upload_bytes == 10 * 1024 * 1024


def test_missing_required_setting_names_the_variable(monkeypatch):
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        config.load_settings()


def test_bad_number_is_reported(monkeypatch):
    set_required(monkeypatch)
    monkeypatch.setenv("MAX_RESULT_ROWS", "lots")
    with pytest.raises(ConfigError, match="MAX_RESULT_ROWS"):
        config.load_settings()
