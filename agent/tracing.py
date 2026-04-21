"""Langfuse wrapper. Falls back to no-op if Langfuse keys are unset so dev-without-keys still works."""
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from agent.config import get_settings

log = logging.getLogger(__name__)

try:
    from langfuse import Langfuse  # type: ignore
except ImportError:  # pragma: no cover
    Langfuse = None  # type: ignore


class _NullSpan:
    def __init__(self, name: str) -> None:
        self.id = str(uuid.uuid4())
        self.name = name

    def update(self, **_: Any) -> None:
        return

    def end(self, **_: Any) -> None:
        return


class Tracer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[Any] = None
        if (
            Langfuse is not None
            and self.settings.LANGFUSE_PUBLIC_KEY
            and self.settings.LANGFUSE_SECRET_KEY
        ):
            try:
                self._client = Langfuse(
                    public_key=self.settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=self.settings.LANGFUSE_SECRET_KEY,
                    host=self.settings.LANGFUSE_HOST,
                )
            except Exception as e:
                log.warning("Langfuse init failed, tracing disabled: %s", e)
                self._client = None

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[Any]:
        if self._client is None:
            yield _NullSpan(name)
            return
        trace = self._client.trace(name=name, metadata=metadata)
        try:
            yield trace
        finally:
            try:
                self._client.flush()
            except Exception:
                pass


_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
