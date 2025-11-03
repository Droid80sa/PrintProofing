import logging
import os
import threading
import queue
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from flask import current_app
except ImportError:  # pragma: no cover - queue can still run outside Flask
    current_app = None


class EmailQueue:
    def __init__(self, log_path: str):
        self.queue: "queue.Queue[Tuple[Callable[..., Any], tuple, Dict[str, Any], Optional[Any]]]" = queue.Queue()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        self.logger = logging.getLogger("email_queue")
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

        self.worker_thread = threading.Thread(target=self._worker, name="EmailQueueWorker", daemon=True)
        self.worker_thread.start()

    def _worker(self) -> None:
        while True:
            func, args, kwargs, meta, app_obj = self.queue.get()
            try:
                if app_obj is not None:
                    with app_obj.app_context():
                        func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
                self.logger.info("Email task succeeded: %s", meta)
            except Exception as exc:
                self.logger.exception("Email task failed: %s", exc)
            finally:
                self.queue.task_done()

    def enqueue(
        self,
        func: Callable[..., Any],
        *args: Any,
        meta: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        app_obj = None
        if current_app is not None:
            try:
                app_obj = current_app._get_current_object()
            except RuntimeError:
                app_obj = None
        self.queue.put((func, args, kwargs, meta or {}, app_obj))


def get_email_queue(log_path: Optional[str] = None) -> EmailQueue:
    # Simple singleton pattern
    global _EMAIL_QUEUE_INSTANCE
    try:
        return _EMAIL_QUEUE_INSTANCE
    except NameError:
        if log_path is None:
            base_dir = os.path.dirname(__file__)
            log_path = os.path.join(base_dir, "logs", "email.log")
        _EMAIL_QUEUE_INSTANCE = EmailQueue(log_path)
        return _EMAIL_QUEUE_INSTANCE


# Initialize default queue on import
EMAIL_QUEUE = get_email_queue()
