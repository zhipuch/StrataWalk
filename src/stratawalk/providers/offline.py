"""Deterministic fixtures for development; not semantic/LLM quality baselines."""
import hashlib
import math
import re
from ..tokenization import prefix


def terms(text):
    return re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", text.lower())


class HashEmbedder:
    """Stable hashed bag-of-words. Collision-prone lexical demo, not a real embedding model."""
    def __init__(self, dimensions=256):
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions
        self.name = "offline-hash-%d" % dimensions

    async def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in terms(text):
                digest = hashlib.sha256(word.encode()).digest()
                vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            vectors.append([v / norm for v in vector])
        return vectors


class ExtractiveSummarizer:
    """Budgeted extracts to exercise construction without a network/model."""
    name = "offline-extractive"

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    async def summarize(self, blocks, budget):
        # Preserve contributions in source order; no invented natural-language summary.
        per_block = max(1, budget // len(blocks))
        pieces = [prefix(b.text.strip(), per_block, self.tokenizer) for b in blocks]
        result = prefix(" ".join(p for p in pieces if p), budget, self.tokenizer).strip()
        if not result:
            raise ValueError("Summary budget is too small")
        return [result]


class OfflinePolicy:
    """A transparent scripted policy, NOT an autonomous reasoning model.

    Search source leaves, collect exact excerpts, finish. The same runtime can
    use ChatPolicy for actual model-selected search and navigation actions.
    """
    async def decide(self, state):
        if not state["evidence"]:
            if state["observations"]:
                return {"tool": "finish", "args": {
                    "answer": "Offline demo could not retrieve source excerpts. Try a more descriptive question, "
                              "check the tool budget, or use --provider compatible for model-directed retrieval.",
                    "insufficient": True}}
            return {"tool": "search", "args": {"query": state["question"], "top_k": 3, "kind": "leaf"}}
        snippets, ids = [], []
        for block_id, record in state["evidence"].items():
            ids.append(block_id)
            snippets.append("[%s] %s" % (block_id, record["text"]))
        return {"tool": "finish", "args": {
            "answer": "Offline demo: retrieved source excerpts (not a synthesized LLM answer).\n\n" + "\n\n".join(snippets),
            "citation_ids": ids}}
