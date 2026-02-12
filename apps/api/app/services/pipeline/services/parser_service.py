"""Pipeline parser service compatibility shim.

Parser implementation moved to `app.services.parser`.
"""

from app.services.parser import (
    CommandContext,
    CommandIntent,
    CommandParser,
    command_parser,
)

# Alias aligned with this module's role.
parser_service = command_parser

__all__ = [
    "CommandIntent",
    "CommandContext",
    "CommandParser",
    "command_parser",
    "parser_service",
]
