class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, *, retryable=False, retry_after=0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


class LostLease(Exception):
    """The worker must stop; another attempt owns this job or it was cancelled."""
