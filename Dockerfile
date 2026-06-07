# Use Python 3.11 slim image
FROM python:3.11-slim

ARG BUILD_COMMIT=unknown
LABEL build.commit="${BUILD_COMMIT}"

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.8.3

# Configure poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Copy the monorepo. The Python distributions live under agentkit/:
#   agentkit/sdk   -> the agentkit SDK
#   agentkit/serve -> the FastAPI + workers service (path-depends on ../sdk)
COPY . .

# Installing the serve distribution pulls in the SDK via its path dependency
# (agentkit/serve -> ../sdk), so a single install gives both.
RUN pip install ./agentkit/serve

# Fail at build time if either package is unimportable (catches stale cached images
# built before the monorepo restructure, where the installed path no longer matches).
RUN python -c "import agentkit; import agentkit_serve"

# Create a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application (the reference service lives in agentkit-serve)
CMD ["uvicorn", "agentkit_serve.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
