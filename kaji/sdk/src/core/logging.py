"""Logging configuration for Kaji SDK with Rich formatting."""

import importlib.util
import logging
import sys
from functools import lru_cache
from importlib import import_module
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import BaseModel, ConfigDict

RICH_AVAILABLE = importlib.util.find_spec("rich") is not None


# Configuration
DATE_FORMAT = "%d %b %Y | %H:%M:%S"
LOGGER_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


class LoggerConfig(BaseModel):
    """Logger configuration model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    handlers: list[logging.Handler]
    format: str | None = None
    date_format: str | None = None
    logger_file: Path | None = None
    level: int = logging.INFO


@lru_cache
def get_logger_config(debug: bool = False) -> LoggerConfig:
    """
    Get logger configuration with Rich handler if not in production.

    Args:
        debug: Enable debug-level logging with locals in tracebacks

    Returns:
        LoggerConfig with appropriate handlers
    """
    log_level = logging.DEBUG if debug else logging.INFO
    log_dir = Path("logs")

    # Try to create logs directory
    try:
        log_dir.mkdir(exist_ok=True)
        logger_file = log_dir / "kaji.log"
    except (OSError, PermissionError):
        logger_file = None

    handlers: list[logging.Handler] = []

    # Use Rich logging if available
    if RICH_AVAILABLE:
        RichHandler = import_module("rich.logging").RichHandler
        install_rich_traceback = import_module("rich.traceback").install

        # Install rich traceback handler for better error display
        install_rich_traceback(
            show_locals=debug,
            width=120,
            extra_lines=3 if debug else 1,
            theme="monokai",
            word_wrap=True,
            suppress=["uvicorn", "starlette"],
        )

        # Create Rich handler
        rich_handler = RichHandler(
            rich_tracebacks=True,
            tracebacks_show_locals=debug,
            tracebacks_width=120,
            tracebacks_extra_lines=3 if debug else 1,
            tracebacks_theme="monokai",
            show_time=False,  # We'll use our own time format
            show_path=True,
            markup=True,
            log_time_format="[%H:%M:%S]",
        )
        rich_handler.setLevel(log_level)
        handlers.append(rich_handler)

        # Add file handler if available
        if logger_file:
            file_handler = RotatingFileHandler(
                logger_file,
                maxBytes=10_485_760,  # 10MB
                backupCount=5,
                encoding="utf-8",
            )
            file_formatter = logging.Formatter(LOGGER_FORMAT, datefmt=DATE_FORMAT)
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(log_level)
            handlers.append(file_handler)

        return LoggerConfig(
            handlers=handlers,
            format=None,  # Rich handles its own formatting
            date_format=DATE_FORMAT,
            logger_file=logger_file,
            level=log_level,
        )

    # Fallback to standard logging
    stdout_handler = logging.StreamHandler(sys.stdout)
    handler_format = logging.Formatter(LOGGER_FORMAT, datefmt=DATE_FORMAT)
    stdout_handler.setFormatter(handler_format)
    stdout_handler.setLevel(log_level)
    handlers.append(stdout_handler)

    # Add file handler if available
    if logger_file:
        file_handler = RotatingFileHandler(
            logger_file, maxBytes=10_485_760, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(handler_format)
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    return LoggerConfig(
        handlers=handlers,
        format=LOGGER_FORMAT,
        date_format=DATE_FORMAT,
        logger_file=logger_file,
        level=log_level,
    )


def setup_logging(debug: bool = False):
    """
    Configure logging for the application with Rich formatting.
    Removes all existing handlers from root logger and propagates to root.

    Args:
        debug: Enable debug-level logging
    """
    # Remove all handlers from root logger and propagate to root logger
    for name in logging.root.manager.loggerDict.keys():
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # Get Rich logging config
    logger_config = get_logger_config(debug=debug)

    # Configure root logger with Rich handlers
    logging.basicConfig(
        level=logger_config.level,
        format=logger_config.format or LOGGER_FORMAT,
        datefmt=logger_config.date_format,
        handlers=logger_config.handlers,
        force=True,  # Override any existing configuration
    )

    # Set specific loggers to appropriate levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.INFO if debug else logging.WARNING)

    # Log startup message
    logger = logging.getLogger(__name__)
    if RICH_AVAILABLE:
        logger.info("[bold green]Rich logging initialized[/bold green]")
    else:
        logger.info("Standard logging initialized")

    return logging.getLogger()
