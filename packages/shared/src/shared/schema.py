"""Base class for every message that crosses a service boundary.

The agent reads untrusted content, and its output is only ever a structured plan
(docs/03-architecture.md, "agent output in a fixed structure"). If a manipulated model
adds a field the schema does not define, the whole message is rejected rather than the
field being silently dropped: an unexpected field is a signal that something is wrong.
(T1-T7)
"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """A message schema that rejects unknown fields and cannot be changed after creation."""

    model_config = ConfigDict(
        # Unknown fields are an error, not ignored.
        extra="forbid",
        # No silent type coercion: "5" is not accepted where an int is expected.
        strict=True,
        # Messages are values; once validated they cannot be modified in place.
        frozen=True,
    )
