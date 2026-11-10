"""Structured logging configuration using structlog."""

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging() -> None:
    """Configure structlog once for the service."""
    env = os.getenv("ENVIRONMENT", "production").lower()
    use_json = env == "production" and not sys.stderr.isatty()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


configure_logging()


def get_logger(name: str = "neutron") -> Any:
    """Return a structured logger bound with the given component name."""
    return structlog.get_logger().bind(component=name)
