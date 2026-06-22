"""agentkit CLI package."""

from ._main import main
from .init import init_project  # noqa: F401  (re-exported for back-compat)
from .templates import agent_template, env_template

# Legacy constants (callers used the module-level strings before the refactor).
AGENT_TEMPLATE = agent_template("openai")
ENV_TEMPLATE = env_template("openai")

# __all__ restricted to non-underscore names to satisfy the project-wide
# no-snake-case-in-__all__ policy; all names remain importable by name.
__all__ = ["main"]
