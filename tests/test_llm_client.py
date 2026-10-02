from types import SimpleNamespace

import pytest
from openai import APIConnectionError, APIStatusError, RateLimitError

from askdata.exceptions import LLMError
from askdata.llm_client import OpenAICompatibleClient


def make_client(create):
    """Build a real client, then swap the network call for our own function."""
    client = OpenAICompatibleClient("http://localhost:1/v1", "key", "model", 5)
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client


def fake_request():
    # Plain stand-ins, so these tests do not depend on which HTTP library
    # the installed openai version happens to use underneath.
    return SimpleNamespace(method="POST", url="http://localhost:1/v1/chat/completions")


def status_error(error_class, code):
    response = SimpleNamespace(status_code=code, headers={}, request=fake_request())
    return error_class("boom", response=response, body=None)


def reply_with(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_returns_the_reply_text():
    client = make_client(lambda **kwargs: reply_with("hello"))
    assert client.complete([{"role": "user", "content": "hi"}]) == "hello"


def test_sends_model_and_zero_temperature():
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return reply_with("ok")

    make_client(create).complete([{"role": "user", "content": "hi"}])
    assert seen["model"] == "model"
    assert seen["temperature"] == 0


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_reply_is_an_error(text):
    client = make_client(lambda **kwargs: reply_with(text))
    with pytest.raises(LLMError, match="empty"):
        client.complete([])


def test_rate_limit_gets_a_friendly_message():
    def create(**kwargs):
        raise status_error(RateLimitError, 429)

    with pytest.raises(LLMError, match="rate limiting"):
        make_client(create).complete([])


def test_other_http_errors_mention_the_status():
    def create(**kwargs):
        raise status_error(APIStatusError, 401)

    with pytest.raises(LLMError, match="HTTP 401"):
        make_client(create).complete([])


def test_connection_problems_mention_the_configured_url():
    def create(**kwargs):
        raise APIConnectionError(request=fake_request())

    with pytest.raises(LLMError, match="configured URL"):
        make_client(create).complete([])
