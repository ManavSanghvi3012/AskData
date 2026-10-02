"""Access a model through an OpenAI compatible chat endpoint.

The application uses a small client interface so the query pipeline does not
depend directly on one provider. The tested configuration uses Groq. Tests use
a fake client and do not require network access or an API key.
"""

from abc import ABC, abstractmethod

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from askdata.exceptions import LLMError

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}


class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: list[Message]) -> str:
        """Send the conversation and return the model's text reply."""


class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float):
        self._base_url = base_url
        self._model = model
        # The SDK already retries a few times with backoff on rate limits
        # and brief network errors, so we do not write our own retry loop.
        self._client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_seconds, max_retries=3
        )

    def complete(self, messages: list[Message]) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0,  # we want the same question to give the same SQL
            )
        except RateLimitError as exc:
            raise LLMError(
                "The model provider is rate limiting requests. Wait a minute and try again."
            ) from exc
        except APIConnectionError as exc:
            raise LLMError(
                f"Could not reach the model at {self._base_url}. "
                "Check the configured URL and your network connection."
            ) from exc
        except APIStatusError as exc:
            raise LLMError(
                f"The model provider returned an error (HTTP {exc.status_code}). "
                "Check LLM_API_KEY and LLM_MODEL."
            ) from exc

        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            raise LLMError("The model returned an empty reply.")
        return content
