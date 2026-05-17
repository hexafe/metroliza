from modules.worker_cancellation import WorkerCancellationMixin


class _Token:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Worker(WorkerCancellationMixin):
    def __init__(self) -> None:
        self.cancellation_token = _Token()
        self.interrupted = False
        self._init_cancellation_state()

    def requestInterruption(self) -> None:
        self.interrupted = True

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


def test_worker_cancellation_mixin_cancels_token_and_interrupts_worker() -> None:
    worker = _Worker()

    assert worker._is_cancelled() is False
    worker.cancel()

    assert worker._is_cancelled() is True
    assert worker.cancellation_token.cancelled is True
    assert worker.interrupted is True
