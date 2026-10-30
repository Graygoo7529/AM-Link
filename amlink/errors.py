class MemoryError(RuntimeError):
    def __init__(self, code: str, status: int = 503, detail=None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail
        self.retryable = status in {408, 425, 429, 500, 502, 503, 504}
