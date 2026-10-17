from typing import List, Protocol
from ..models import Block


class Embedder(Protocol):
    name: str
    async def embed(self, texts: List[str]) -> List[List[float]]: ...


class ChatModel(Protocol):
    name: str
    async def complete(self, messages: List[dict], *, max_tokens: int) -> str: ...


class Summarizer(Protocol):
    name: str
    async def summarize(self, blocks: List["Block"], budget: int) -> List[str]: ...
