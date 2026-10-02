from askdata.llm_client import LLMClient


class FakeLLM(LLMClient):
    """Replays scripted replies and remembers what it was sent."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self._replies.pop(0)
