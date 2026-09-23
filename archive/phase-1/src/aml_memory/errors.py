class IdempotencyConflictError(RuntimeError):
    """The same request ID was reused with a different payload."""


class AuthenticationError(RuntimeError):
    """The caller did not provide the configured memory-system credential."""

