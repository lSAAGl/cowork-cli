"""Backend implementations for AI model invocation."""

from cowork.backends.base import Backend, BackendResult
from cowork.backends.claude import ClaudeBackend

__all__ = ["Backend", "BackendResult", "ClaudeBackend"]
