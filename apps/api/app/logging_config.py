"""Logging configuration for Modal API with Rich formatting."""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

try:
    from rich.console import Console
    from rich.logging import RichHandler
    from rich.traceback import install as install_rich_traceback
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def setup_logging(debug: bool = False):
    """
    Configure logging for the application with Rich formatting.
    
    Args:
        debug: Enable debug-level logging
    """
    # Set log level
    log_level = logging.DEBUG if debug else logging.INFO
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    if RICH_AVAILABLE:
        # Install rich traceback handler for better error display
        install_rich_traceback(
            show_locals=debug,
            width=120,
            extra_lines=3,
            theme="monokai",
            word_wrap=True,
            suppress=[
                "uvicorn",
                "starlette",
            ]
        )
        
        # Create Rich console for logging
        console = Console(
            file=sys.stdout,
            force_terminal=True,  # Force colors in Docker
            width=120,
            color_system="auto"
        )
        
        # Create Rich handler with custom formatting
        rich_handler = RichHandler(
            console=console,
            level=log_level,
            show_time=True,
            show_level=True,
            show_path=True,
            enable_link_path=False,  # Disable in Docker
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=debug,
            tracebacks_width=120,
            tracebacks_extra_lines=3,
            tracebacks_theme="monokai",
            log_time_format="[%Y-%m-%d %H:%M:%S]",
            omit_repeated_times=False,
        )
        
        # Add Rich handler
        root_logger.addHandler(rich_handler)
        root_logger.info("🚀 Rich logging initialized")
    else:
        # Fallback to standard logging if Rich is not available
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(detailed_formatter)
        
        root_logger.addHandler(console_handler)
        root_logger.warning("Rich logging not available, using standard logging")
    
    # Optionally add file handlers if logs directory exists
    log_dir = Path("/app/logs")
    if log_dir.exists() or log_dir.parent.exists():
        try:
            log_dir.mkdir(exist_ok=True)
            
            # Plain text formatter for file logs
            file_formatter = logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # File handler for all logs (rotating)
            file_handler = RotatingFileHandler(
                log_dir / "app.log",
                maxBytes=10_485_760,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
            
            # File handler for errors only (rotating)
            error_handler = RotatingFileHandler(
                log_dir / "error.log",
                maxBytes=10_485_760,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(file_formatter)
            root_logger.addHandler(error_handler)
        except (OSError, PermissionError) as e:
            # If we can't write to files, just use console logging
            root_logger.warning(f"Could not set up file logging: {e}")
    
    # Set specific loggers to appropriate levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    
    # Log startup message
    root_logger.info("🚀 Rich logging initialized")
    
    return root_logger
