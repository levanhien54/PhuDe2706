import structlog
import logging
import sys


def _log_file_path() -> str:
    """Absolute path of the orchestrator log file, derived from settings.data_dir so logs land
    next to the rest of the app data (not in a cwd-relative 'data/' that depends on where the
    process happened to be started)."""
    import os
    from orchestrator.config import get_settings
    return os.path.join(get_settings().data_dir, "orchestrator.log")


def setup_logging(log_level: str = "INFO") -> None:
    # Force UTF-8 on Windows
    if sys.platform == "win32":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")

    # Setup RotatingFileHandler
    import logging.handlers
    import os

    log_path = _log_file_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[file_handler, console_handler]
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def bind_job_context(job_id: str, filename: str) -> None:
    structlog.contextvars.bind_contextvars(job_id=job_id, filename=filename)


def clear_job_context() -> None:
    structlog.contextvars.clear_contextvars()
