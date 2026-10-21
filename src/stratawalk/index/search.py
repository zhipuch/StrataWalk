"""Exact cosine search over every block; replace this module for ANN scale."""
import heapq
import math
import sys
from dataclasses import dataclass
from typing import List
from ..models import TreeIndex


@dataclass
class SearchHit:
    node_id: str
    block_id: str
    score: float
    level: int
    kind: str
    start: int
    end: int
    text: str


def _vector_stats(vector, dimension=None):
    if not isinstance(vector, (list, tuple)) or not vector:
        raise ValueError("Embedding must be a nonempty numeric vector")
    if dimension is not None and len(vector) != dimension:
        raise ValueError("Query and index embedding dimensions differ")
    try:
        finite = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                     and math.isfinite(v) for v in vector)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("Embedding must contain finite numbers")
    norm = math.hypot(*vector)
    scale = 1.0
    if norm and (not math.isfinite(norm) or norm < sys.float_info.min):
        scale = max(abs(v) for v in vector)
        norm = math.hypot(*(v / scale for v in vector))
    return scale, norm


def _score(unit, vector, scale, norm):
    if not norm:
        return 0.0
    products = (a * b for a, b in zip(unit, vector)) if scale == 1 else (
        a * (b / scale) for a, b in zip(unit, vector))
    return max(-1.0, min(1.0, math.fsum(products) / norm))


def cosine(left, right):
    scale, norm = _vector_stats(left)
    other_scale, other_norm = _vector_stats(right, len(left))
    if not norm or not other_norm:
        return 0.0
    return _score([v / scale / norm for v in left], right, other_scale, other_norm)


class SemanticSearch:
    def __init__(self, index: TreeIndex, embedder):
        self.index, self.embedder = index, embedder
        if index.metadata.get("embedder") != embedder.name:
            raise ValueError("Embedding provider/model differs from this index; use the build-time --provider, --base-url and --embedding-model, or rebuild")
        # A static index is reused across questions. Cache only scalar statistics,
        # leaving embeddings in place rather than duplicating all vector data.
        self._entries, self._dimension = [], None
        for node in index.nodes.values():
            blocks = []
            for block in node.blocks:
                scale, norm = _vector_stats(block.embedding, self._dimension)
                self._dimension = len(block.embedding)
                if norm:
                    blocks.append((block, scale, norm))
            if blocks:
                self._entries.append((node, blocks))
        if self._dimension is None:
            raise ValueError("Index contains no searchable blocks; rebuild the index")

    async def search(self, query, top_k=5, kind=None, min_level=None, max_level=None,
                     *, unique_nodes=False, exclude_nodes=None) -> List[SearchHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k must be 1..50")
        if kind is not None and kind not in {"leaf", "summary", "chapter", "root"}:
            raise ValueError("Unknown node kind")
        if min_level is not None and (not isinstance(min_level, int) or isinstance(min_level, bool) or min_level < 0):
            raise ValueError("Invalid min_level")
        if max_level is not None and (not isinstance(max_level, int) or isinstance(max_level, bool) or max_level < 0):
            raise ValueError("Invalid max_level")
        if min_level is not None and max_level is not None and min_level > max_level:
            raise ValueError("min_level exceeds max_level")
        entries = [(node, blocks) for node, blocks in self._entries
                   if (not exclude_nodes or node.id not in exclude_nodes)
                   and (kind is None or node.kind == kind)
                   and (min_level is None or node.level >= min_level)
                   and (max_level is None or node.level <= max_level)]
        if not entries:
            return []
        vectors = await self.embedder.embed([query])
        if not isinstance(vectors, (list, tuple)) or len(vectors) != 1:
            raise ValueError("Query embedder must return exactly one vector")
        vector = vectors[0]
        scale, norm = _vector_stats(vector, self._dimension)
        if not norm:
            raise ValueError("Query embedding has zero magnitude; try a more descriptive question")
        unit = [v / scale / norm for v in vector]

        def key(row):
            score, node, block = row
            return -score, node.start, node.id, block.id

        def candidates():
            for node, blocks in entries:
                best = None
                for block, block_scale, block_norm in blocks:
                    row = (_score(unit, block.embedding, block_scale, block_norm), node, block)
                    if not unique_nodes:
                        yield row
                    elif best is None or key(row) < key(best):
                        best = row
                if unique_nodes and best is not None:
                    yield best

        ranked = heapq.nsmallest(top_k, candidates(), key=key)
        return [SearchHit(node.id, block.id, score, node.level, node.kind, node.start, node.end, block.text)
                for score, node, block in ranked]
