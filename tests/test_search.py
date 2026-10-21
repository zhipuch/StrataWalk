import math
import random
import unittest

from stratawalk.index.search import SemanticSearch, cosine
from test_index import builder, TEXT


class FixedEmbedder:
    name = "search-fixture"

    def __init__(self, response=None):
        self.response = [[0.2, -0.4, 0.8]] if response is None else response
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        return self.response


class NumericTests(unittest.TestCase):
    def test_cosine_handles_extreme_finite_vectors(self):
        for magnitude in (1.7e308, 1e200, 1e-200, 1e-320):
            with self.subTest(magnitude=magnitude):
                self.assertAlmostEqual(cosine([magnitude, magnitude], [magnitude, magnitude]), 1)
                self.assertAlmostEqual(cosine([magnitude, magnitude], [-magnitude, -magnitude]), -1)
                self.assertAlmostEqual(cosine([magnitude, 0], [0, magnitude]), 0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0)

    def test_invalid_vectors_are_rejected(self):
        for vector in ([], None, [True], ["1"], [float("nan")], [float("inf")], [10 ** 1000]):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                cosine(vector, [1])
        with self.assertRaisesRegex(ValueError, "dimensions"):
            cosine([1, 2], [1])


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class Topics:
            async def summarize(self, blocks, budget):
                return ["alpha", "beta"] if budget >= 9 else ["a"]
        instance = builder()
        instance.summarizer = Topics()
        self.index = await instance.build(TEXT)
        self.index.metadata["embedder"] = FixedEmbedder.name
        rng = random.Random(42)
        for block in self.index.block_map().values():
            block.embedding = [rng.randrange(-3, 4) for _ in range(3)]

    async def test_top_k_matches_exhaustive_ranking_and_distinct_nodes(self):
        embedder = FixedEmbedder()
        search = SemanticSearch(self.index, embedder)
        query = embedder.response[0]
        for unique in (False, True):
            expected = []
            for node in self.index.nodes.values():
                for block in node.blocks:
                    norm = math.sqrt(sum(v * v for v in block.embedding))
                    if norm:
                        score = sum(a * b for a, b in zip(query, block.embedding)) / (
                            math.sqrt(sum(v * v for v in query)) * norm)
                        expected.append((score, node.start, node.id, block.id))
            expected.sort(key=lambda row: (-row[0], *row[1:]))
            if unique:
                seen, distinct = set(), []
                for row in expected:
                    if row[2] not in seen:
                        distinct.append(row)
                        seen.add(row[2])
                expected = distinct
            actual = await search.search("question", top_k=7, unique_nodes=unique)
            self.assertEqual([h.block_id for h in actual], [row[3] for row in expected[:7]])
            for hit, row in zip(actual, expected):
                self.assertAlmostEqual(hit.score, row[0])

    async def test_empty_candidates_skip_query_embedding(self):
        embedder = FixedEmbedder()
        search = SemanticSearch(self.index, embedder)
        self.assertEqual(await search.search("question", exclude_nodes=set(self.index.nodes)), [])
        self.assertEqual(await search.search("question", kind="root", max_level=0), [])
        self.assertEqual(embedder.calls, 0)

    async def test_zero_blocks_are_not_hits_and_equal_scores_have_stable_order(self):
        blocks = list(self.index.block_map().values())
        zero_id = blocks[0].id
        for block in blocks:
            block.embedding = [1, 0, 0]
        blocks[0].embedding = [0, 0, 0]
        embedder = FixedEmbedder([[1, 0, 0]])
        search = SemanticSearch(self.index, embedder)
        hits = await search.search("question", top_k=50)
        expected = sorted((node.start, node.id, block.id)
                          for node in self.index.nodes.values() for block in node.blocks if block.id != zero_id)
        self.assertEqual([hit.block_id for hit in hits], [row[2] for row in expected[:50]])
        for block in blocks:
            block.embedding = [0, 0, 0]
        empty_search = SemanticSearch(self.index, embedder)
        previous_calls = embedder.calls
        self.assertEqual(await empty_search.search("question"), [])
        self.assertEqual(embedder.calls, previous_calls)

    async def test_malformed_and_zero_query_vectors_fail_clearly(self):
        for response in ([], [[], []], [[]], [None], [[1]], [[True, 0, 0]],
                         [[float("nan"), 0, 0]], [[0, 0, 0]]):
            with self.subTest(response=response), self.assertRaises(ValueError):
                await SemanticSearch(self.index, FixedEmbedder(response)).search("question")

    async def test_filtered_search_and_exclusions(self):
        search = SemanticSearch(self.index, FixedEmbedder())
        hits = await search.search("question", kind="leaf", min_level=0, max_level=0)
        self.assertTrue(hits)
        self.assertTrue(all(hit.kind == "leaf" and hit.level == 0 for hit in hits))
        omitted = {hit.node_id for hit in hits}
        rest = await search.search("question", kind="leaf", exclude_nodes=omitted)
        self.assertTrue(all(hit.node_id not in omitted for hit in rest))
        with self.assertRaises(ValueError):
            await search.search("question", min_level=True)
