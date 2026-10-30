class MemoryError(Exception):
    """Safe public error: never includes provider responses or user text."""

    def __init__(self, code: str, status: int = 503, *, detail=None):
        super().__init__(code)
        self.code, self.status = code, status
        self.retryable = status in {408, 409, 425, 429, 500, 502, 503, 504}
        if detail is None and code.startswith('provider_'):
            detail = {'format_version': 1, 'layer': 'dependency', 'code': code}
        self.detail = detail
