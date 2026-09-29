"""Data connectors (GitHub, Notion) using httpx and keyring-stored tokens.

Tokens live in the OS keyring; nothing is written to config.json. Connectors
are disabled unless explicitly enabled in config AND a token is present.
"""

from . import github, notion  # noqa: F401

__all__ = ["github", "notion"]