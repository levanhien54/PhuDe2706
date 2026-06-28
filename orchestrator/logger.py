import structlog
import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    # Setup RotatingFileHandler
    import logging.handlers
    import os
    
    os.makedirs("data", exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        "data/orchestrator.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
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
