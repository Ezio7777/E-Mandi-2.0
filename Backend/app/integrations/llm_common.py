"""Text-LLM contract shared by agents (pricing explanations now; voice answers later)."""
from typing import Protocol


class LLMProviderError(Exception):
    """kind: timeout | api_error | invalid_response | not_configured"""

    def __init__(self, kind: str, provider: str) -> None:
        super().__init__(f"{provider}:{kind}")
        self.kind, self.provider = kind, provider


class TextLLM(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def complete_json(self, system: str, user: str) -> str: ...
