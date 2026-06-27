import structlog
import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
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
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def bind_job_context(job_id: str, filename: str) -> None:
    structlog.contextvars.bind_contextvars(job_id=job_id, filename=filename)


def clear_job_context() -> None:
    structlog.contextvars.clear_contextvars()
