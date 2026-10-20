"""Explicit token accounting; source offsets always refer to Python characters."""
from typing import Protocol, List, Tuple


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


class ByteTokenizer:
    """Conservative UTF-8 byte budget, NOT a model-specific token count.

    Useful offline and for byte-level tokenizers. Supply the actual provider's
    tokenizer for calibrated context accounting, especially with other families.
    """
    name = "utf8-bytes"

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class TiktokenTokenizer:
    def __init__(self, encoding: str):
        try:
            import tiktoken
        except ImportError as exc:
            raise ImportError("Install stratawalk[tokenizer] to use tiktoken") from exc
        self.encoding = tiktoken.get_encoding(encoding)
        self.name = "tiktoken:" + encoding

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text, disallowed_special=()))


def _prefix_end(text: str, start: int, budget: int, tokenizer: Tokenizer) -> int:
    """Find a fitting boundary using local probes, without scanning the suffix."""
    if budget <= 0:
        return start
    lo = start
    width = max(1, budget)
    hi = min(len(text), start + width)
    while tokenizer.count(text[start:hi]) <= budget:
        lo = hi
        if hi == len(text):
            return hi
        width *= 2
        hi = min(len(text), start + width)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tokenizer.count(text[start:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    # Always verify the result, including tokenizers with boundary effects.
    while lo > start and tokenizer.count(text[start:lo]) > budget:
        lo -= 1
    return lo


def prefix(text: str, budget: int, tokenizer: Tokenizer) -> str:
    """Return a Unicode-safe prefix fitting the budget (possibly empty)."""
    return text[:_prefix_end(text, 0, budget, tokenizer)]


def chunk_spans(text: str, size: int, overlap: int, tokenizer: Tokenizer) -> List[Tuple[int, int]]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require chunk_size > overlap >= 0")
    spans = []
    start = 0
    while start < len(text):
        end = _prefix_end(text, start, size, tokenizer)
        if end == start:
            raise ValueError("Chunk budget cannot fit one Unicode character")
        spans.append((start, end))
        if end == len(text):
            break
        # Find a suffix within the overlap budget; always advance by >= 1 char.
        back = end
        while back > start + 1 and tokenizer.count(text[back - 1:end]) <= overlap:
            back -= 1
        start = max(start + 1, back)
    return spans
