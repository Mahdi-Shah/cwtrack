"""Safe, low-detail failure categories shared across adapters and read models."""

FAILURE_KINDS = frozenset({
    "transport_error",
    "authentication_required",
    "parser_error",
    "unexpected_response",
})


def is_failure_kind(value) -> bool:
    """Accept only fixed categories; never persist raw server or exception text."""
    return isinstance(value, str) and value in FAILURE_KINDS
