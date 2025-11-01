"""Logging configuration for Modal API."""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logging(debug: bool = False):
    """
    Configure logging for the application.
    
    Args:
        debug: Enable debug-level logging
    """
    # Set log level
    log_level = logging.DEBUG if debug else logging.INFO
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (stdout) - primary handler for Docker
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(detailed_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Add console handler (Docker will capture this)
    root_logger.addHandler(console_handler)
    
    # Optionally add file handlers if logs directory exists
    log_dir = Path("/app/logs")
    if log_dir.exists() or log_dir.parent.exists():
        try:
            log_dir.mkdir(exist_ok=True)
            
            # File handler for all logs (rotating)
            file_handler = RotatingFileHandler(
                log_dir / "app.log",
                maxBytes=10_485_760,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(file_handler)
            
            # File handler for errors only (rotating)
            error_handler = RotatingFileHandler(
                log_dir / "error.log",
                maxBytes=10_485_760,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(detailed_formatter)
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
    
    return root_logger
