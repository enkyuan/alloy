"""Legacy voice-agent tool abstractions.

This package houses the older ``ToolDefinition`` ABC and the system tools
(``EndCallTool``, ``TransferCallTool``, etc.) that were built against the
pre-``ToolSpec`` registry model.

These are **not part of the public SDK API** and are not exported from
``agentkit`` or ``agentkit.modalities.voice``.  New voice tools should be
implemented using ``ToolSpec`` + ``ToolRegistry`` (``agentkit.runtime.tools``).

Kept here so existing serve-side voice agents continue to work while the
migration to the new model is in progress.
"""
