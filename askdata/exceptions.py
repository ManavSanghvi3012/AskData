"""Application errors that can be shown as clear messages in the interface.

All expected errors inherit from AskDataError so the interface can handle
them consistently.
"""


class AskDataError(Exception):
    """Base class for all expected, user-explainable errors."""


class ConfigError(AskDataError):
    """A required setting is missing or has a bad value."""


class DataLoadError(AskDataError):
    """The uploaded file could not be read or is not usable."""


class UnsafeQueryError(AskDataError):
    """The SQL broke one of our safety rules (or was not valid SQL)."""


class QueryExecutionError(AskDataError):
    """The SQL was allowed but failed or timed out while running."""


class LLMError(AskDataError):
    """The model provider could not be reached or returned nothing useful."""


class QuestionNotAnswerableError(AskDataError):
    """The model decided the question cannot be answered from this table."""
