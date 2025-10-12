"""Database configuration and session management."""
import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# Create database engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Test connections before using
    pool_size=5,  # Maximum number of database connections
    max_overflow=10,  # Maximum overflow size of the pool
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=settings.DEBUG
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency to get database session.
    
    Yields:
        Session: SQLAlchemy database session
        
    Note:
        This is used as a FastAPI dependency to manage database sessions.
        The session is automatically closed after the request is complete.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()
