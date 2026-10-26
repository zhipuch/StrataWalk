import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from stratawalk import BuildConfig, IndexBuilder, load_index, save_index
from stratawalk.index.search import SemanticSearch
from stratawalk.models import Block, Node, Section, TreeIndex
from stratawalk.parsing import MarkdownSectionParser
from stratawalk.providers.offline import ExtractiveSummarizer, HashEmbedder
from stratawalk.tokenization import ByteTokenizer, chunk_spans, prefix

TEXT = "# Report\n\n## Alpha\n" + "alpha apples evidence. " * 35 + "\n## Beta\n" + "beta oranges memory. " * 40


def builder(**kwargs):
    tokenizer = ByteTokenizer()
    config = BuildConfig(chunk_size=100, chunk_overlap=20, summary_size=48,
                         reduction_input=220, max_children=4, **kwargs)
    return IndexBuilder(ExtractiveSummarizer(tokenizer), HashEmbedder(), config=config)


class IndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.index = await builder().build(TEXT, "report.md")

    async def test_full_coverage_order_and_budget(self):
        self.index.validate()
        tokenizer = ByteTokenizer()
        leaves = sorted((n for n in self.index.nodes.values() if n.kind == "leaf"), key=lambda n: n.start)
        covered = set()
        for leaf in leaves:
            covered.update(range(leaf.start, leaf.end))
            self.assertLessEqual(tokenizer.count(leaf.blocks[0].text), 100)
        self.assertEqual(covered, set(range(len(TEXT))))
        chapters = [n for n in self.index.nodes.values() if n.kind == "chapter"]
        self.assertEqual(len(chapters), 3)  # preamble is preserved
        self.assertGreater(self.index.nodes[self.index.root_id].level, 2)
        for node in self.index.nodes.values():
            if node.kind != "leaf":
                self.assertLessEqual(sum(tokenizer.count(b.text) for b in node.blocks), 48)

    async def test_round_trip_and_corrupt_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            save_index(self.index, path)
            restored = load_index(path)
            self.assertEqual(restored, self.index)
            data = path.read_text().replace('"schema_version": 1', '"schema_version": 99')
            path.write_text(data)
            with self.assertRaises(ValueError):
                load_index(path)
        corrupt = deepcopy(self.index)
        corrupt.nodes[corrupt.root_id].children.reverse()
        with self.assertRaises(ValueError):
            corrupt.validate()

    async def test_bidirectional_links_checksum_and_vector_integrity(self):
        leaf_id = next(n.id for n in self.index.nodes.values() if n.kind == "leaf")
        corrupt = deepcopy(self.index)
        corrupt.nodes[leaf_id].parent = None
        with self.assertRaisesRegex(ValueError, "parent link"):
            corrupt.validate()
        corrupt = deepcopy(self.index)
        corrupt.source_text += "changed"
        with self.assertRaisesRegex(ValueError, "checksum"):
            corrupt.validate()
        corrupt = deepcopy(self.index)
        corrupt.nodes[leaf_id].blocks[0].embedding[0] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            corrupt.validate()
        corrupt = deepcopy(self.index)
        corrupt.nodes[corrupt.root_id].children[0] = "missing"
        with self.assertRaisesRegex(ValueError, "Missing child"):
            corrupt.validate()

    async def test_wrong_field_types_in_saved_index_fail_clearly(self):
        original = asdict(self.index)
        node_id = self.index.root_id
        corruptions = (
            lambda data: data.update(schema_version=True),
            lambda data: data.update(metadata=[]),
            lambda data: data["sections"][0].update(id=[]),
            lambda data: data["nodes"][node_id].update(level=True),
            lambda data: data["nodes"][node_id].update(start=0.0),
            lambda data: data["nodes"][node_id].update(parent=[]),
            lambda data: data["nodes"][node_id].update(children="bad"),
            lambda data: data["nodes"][node_id]["blocks"][0].update(text=["bad"]),
            lambda data: data["nodes"][node_id]["blocks"][0].update(source_block_ids=[[]]),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.json"
            for number, mutate in enumerate(corruptions):
                data = deepcopy(original)
                mutate(data)
                path.write_text(json.dumps(data))
                with self.subTest(case=number), self.assertRaisesRegex(ValueError, "Invalid index file"):
                    load_index(path)

    async def test_deep_valid_tree_does_not_depend_on_python_recursion_limit(self):
        source, nodes, previous = "x", {}, None
        for level in range(1500):
            node_id = "n%06d" % level
            kind = "leaf" if level == 0 else "chapter" if level == 1 else "summary"
            node = Node(node_id, kind, level, 0, 1, "s0",
                        [Block(node_id + ":b0", source, [1.0],
                               [previous.blocks[0].id] if previous else [])],
                        [previous.id] if previous else [])
            if previous:
                previous.parent = node_id
            nodes[node_id], previous = node, node
        previous.kind, previous.section_id = "root", None
        index = TreeIndex(hashlib.sha256(source.encode()).hexdigest(), "deep.txt", source,
                          previous.id, nodes, [Section("s0", "Document", 0, 1)])
        index.validate()

    async def test_multiscale_search_and_provider_mismatch(self):
        search = SemanticSearch(self.index, HashEmbedder())
        hits = await search.search("beta oranges memory", 5, "leaf")
        self.assertTrue(all(h.kind == "leaf" for h in hits))
        self.assertIn("beta", hits[0].text.lower())
        roots = await search.search("report", 1, "root")
        self.assertEqual(roots[0].node_id, self.index.root_id)
        with self.assertRaises(ValueError):
            SemanticSearch(self.index, HashEmbedder(64))
        with self.assertRaises(ValueError):
            await search.search("query", 0)

    async def test_concurrent_calls_are_bounded(self):
        class Observed(ExtractiveSummarizer):
            active = peak = 0
            async def summarize(self, blocks, budget):
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.001)
                    return await super().summarize(blocks, budget)
                finally:
                    self.active -= 1
        observed = Observed(ByteTokenizer())
        instance = builder(concurrency=2)
        instance.summarizer = observed
        await instance.build(TEXT)
        self.assertEqual(observed.peak, 2)

    async def test_single_tiny_document(self):
        index = await builder().build("中")
        index.validate()
        self.assertEqual(index.nodes[index.root_id].kind, "root")
        with self.assertRaises(ValueError):
            await builder().build("  ")

    async def test_summary_blocks_respect_embedding_limit(self):
        class Paragraphs:
            async def summarize(self, blocks, budget):
                return ["x" * min(budget, 64)]
        config = BuildConfig(chunk_size=40, chunk_overlap=5, embedding_limit=40,
                             summary_size=80, reduction_input=160, max_children=4)
        index = await IndexBuilder(Paragraphs(), HashEmbedder(), config=config).build("Evidence " * 60)
        self.assertTrue(any(len(n.blocks) > 1 for n in index.nodes.values()))
        for block in index.block_map().values():
            self.assertLessEqual(ByteTokenizer().count(block.text), 40)
            self.assertEqual(len(block.embedding), 256)

    async def test_nonshrinking_summary_is_rejected(self):
        class Bad:
            async def summarize(self, blocks, budget):
                return ["x" * (budget + 1)]
        instance = builder()
        instance.summarizer = Bad()
        with self.assertRaisesRegex(ValueError, "output budget"):
            await instance.build(TEXT)

    async def test_invalid_parser_fails_before_model_work(self):
        class Parser:
            def __init__(self, sections):
                self.sections = sections
            def parse(self, text):
                return self.sections
        class NoModelCalls:
            async def summarize(self, *args):
                raise AssertionError("Invalid parser must fail before model work")
        cases = ([], [Section("s0", "partial", 0, len(TEXT) - 1)],
                 [Section("s0", "gap", 1, len(TEXT))],
                 [Section("s0", "first", 0, 1), Section("s0", "duplicate", 1, len(TEXT))])
        for sections in cases:
            with self.subTest(sections=sections):
                instance = builder()
                instance.parser, instance.summarizer = Parser(sections), NoModelCalls()
                with self.assertRaisesRegex(ValueError, "Parser"):
                    await instance.build(TEXT)


class SourceTests(unittest.TestCase):
    def test_chunking_counter_work_scales_with_input_not_remaining_suffixes(self):
        class CountingTokenizer:
            def __init__(self):
                self.scanned = 0
            def count(self, text):
                self.scanned += len(text)
                return len(text)
        workloads = []
        for length in (10000, 40000):
            tokenizer = CountingTokenizer()
            spans = chunk_spans("x" * length, 128, 0, tokenizer)
            self.assertEqual(spans[-1][1], length)
            self.assertTrue(all(end - start <= 128 for start, end in spans))
            workloads.append(tokenizer.scanned)
        self.assertLess(workloads[1], 5 * workloads[0])

    def test_prefix_handles_unicode_and_tokenizers_with_compressed_text(self):
        class Compressed:
            def count(self, text):
                return (len(text) + 7) // 8
        self.assertEqual(prefix("x" * 100, 3, Compressed()), "x" * 24)
        self.assertEqual(prefix("中🙂a", 7, ByteTokenizer()), "中🙂")
        self.assertEqual(prefix("中", 2, ByteTokenizer()), "")
        self.assertEqual(prefix("anything", 0, ByteTokenizer()), "")
        self.assertEqual(prefix("", 10, ByteTokenizer()), "")

    def test_unicode_overlap_and_exact_offsets(self):
        text = "树索引与agent🙂" * 10
        spans = chunk_spans(text, 30, 8, ByteTokenizer())
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        for previous, current in zip(spans, spans[1:]):
            self.assertGreater(current[0], previous[0])
            self.assertLessEqual(current[0], previous[1])
            self.assertLessEqual(ByteTokenizer().count(text[current[0]:current[1]]), 30)

    def test_fenced_headings_are_not_sections(self):
        text = "# Report\n## First\n```md\n## Fake\n```\n## Second\nText\n"
        sections = MarkdownSectionParser().parse(text)
        self.assertEqual([s.title for s in sections], ["Preamble", "First", "Second"])
        self.assertEqual("".join(text[s.start:s.end] for s in sections), text)

    def test_fence_with_trailing_text_does_not_end_a_code_block(self):
        for fence in ("```", "~~~~"):
            text = ("# Report\r\n## Real\r\n" + fence + "python\r\nx = 1\r\n" + fence
                    + " still code\r\n## Not a chapter\r\n" + fence + " \t\r\n## After\r\nBody\r\n")
            with self.subTest(fence=fence):
                sections = MarkdownSectionParser().parse(text)
                self.assertEqual([s.title for s in sections], ["Preamble", "Real", "After"])
                self.assertEqual("".join(text[s.start:s.end] for s in sections), text)

    def test_backticks_in_info_text_do_not_open_a_fence(self):
        text = "# Report\n```inline `code`\n## Visible\nBody\n"
        self.assertEqual([s.title for s in MarkdownSectionParser().parse(text)], ["Preamble", "Visible"])

    def test_invalid_reduction_budget(self):
        with self.assertRaises(ValueError):
            BuildConfig(reduction_input=100).validate()

    def test_whitespace_preamble_and_long_blank_runs(self):
        # Blank regions are still source data and must retain exact coverage.
        text = " " * 250 + "\n## Chapter\nContent."
        index = asyncio.run(builder().build(text))
        index.validate()
        self.assertEqual(index.source_text, text)
