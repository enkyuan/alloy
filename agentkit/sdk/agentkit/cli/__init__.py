"""agentkit CLI package."""

from ._main import main
from .init import init_project  # noqa: F401  (re-exported for back-compat)
from .templates import agent_template, env_template

# Legacy constants (callers used the module-level strings before the refactor).
AGENT_TEMPLATE = agent_template("openai")
ENV_TEMPLATE = env_template("openai")

# Public CLI entry point. ``init_project``, ``agent_template``, and
# ``env_template`` remain importable via attribute lookup; they are not
# elevated to ``__all__`` because they are internal helpers.
__all__ = ["main"]
