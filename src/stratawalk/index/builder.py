"""Bottom-up ordered reduction with bounded concurrency and explicit budgets."""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from ..models import Block, Node, TreeIndex
from ..parsing import MarkdownSectionParser
from ..tokenization import ByteTokenizer, chunk_spans
from ..providers.compatible import LLMSummarizer


@dataclass
class BuildConfig:
    chunk_size: int = 768
    chunk_overlap: int = 96
    embedding_limit: int = 1024
    reduction_input: int = 4096
    summary_size: int = 512
    context_limit: int = 16384
    safety_margin: int = 512
    max_children: int = 8
    concurrency: int = 4
    embedding_batch: int = 32

    def validate(self):
        for key, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("%s must be a nonnegative integer" % key)
        if not 0 <= self.chunk_overlap < self.chunk_size <= self.embedding_limit:
            raise ValueError("Require 0 <= overlap < chunk_size <= embedding_limit")
        if self.max_children < 2 or min(self.concurrency, self.embedding_batch, self.summary_size) < 1:
            raise ValueError("Invalid grouping/concurrency/batch/summary configuration")
        # Every pair fits, so each nontrivial reduction shrinks node count.
        if 2 * max(self.chunk_size, self.summary_size) > self.reduction_input:
            raise ValueError("reduction_input must fit at least two chunks or summaries")
        if self.reduction_input + self.summary_size + 128 + self.safety_margin >= self.context_limit:
            raise ValueError("Context limit leaves no room for prompt/serialization overhead")


class IndexBuilder:
    def __init__(self, summarizer, embedder, *, config=None, parser=None, tokenizer=None):
        self.summarizer, self.embedder = summarizer, embedder
        self.config = config or BuildConfig()
        self.config.validate()
        self.parser = parser or MarkdownSectionParser()
        self.tokenizer = tokenizer or ByteTokenizer()

    async def build(self, text: str, source_name="document") -> TreeIndex:
        """Build in isolated local state; a failed call never leaves a partial index."""
        sections = self.parser.parse(text)
        nodes = {}
        gate = asyncio.Semaphore(self.config.concurrency)
        count = 0

        def new_id():
            nonlocal count
            node_id = "n%06d" % count
            count += 1
            return node_id

        def weight(node):
            return sum(self.tokenizer.count(b.text) for b in node.blocks)

        def groups(frontier):
            result, group, used = [], [], 0
            for node in frontier:
                cost = weight(node)
                if group and (used + cost > self.config.reduction_input or len(group) >= self.config.max_children):
                    result.append(group)
                    group, used = [], 0
                group.append(node)
                used += cost
            if group:
                result.append(group)
            if len(frontier) > 1 and len(result) >= len(frontier):
                raise ValueError("Reduction cannot make progress; increase the input budget")
            return result

        async def parent(node_id, children, kind, section_id):
            blocks = [b for n in children for b in n.blocks]
            input_size = sum(self.tokenizer.count(b.text) for b in blocks)
            target = min(self.config.summary_size, max(4, input_size // 2))
            if isinstance(self.summarizer, LLMSummarizer):
                messages = self.summarizer.messages(blocks, target)
                # Includes the actual serialized block identifiers/prompt plus
                # per-message framing allowance and the full completion reserve.
                used = self.tokenizer.count(json.dumps(messages, ensure_ascii=False)) + 32
                if used + target + 128 + self.config.safety_margin > self.config.context_limit:
                    raise ValueError("Serialized summary request exceeds context budget; lower reduction_input/max_children")
            # Unary wrappers need no model call when the existing content fits.
            # This also preserves very short or whitespace-only source spans.
            passthrough = len(children) == 1 and input_size <= self.config.summary_size
            if passthrough:
                paragraphs = [b.text for b in blocks]
                target = self.config.summary_size
            elif not any(b.text.strip() for b in blocks):
                paragraphs = ["[blank]" if target >= 7 else "-"]
            else:
                async with gate:
                    paragraphs = await self.summarizer.summarize(blocks, target)
            if not paragraphs or any(not isinstance(p, str) or (not p if passthrough else not p.strip()) for p in paragraphs):
                raise ValueError("Summarizer returned empty/invalid blocks")
            paragraphs = [p if passthrough else p.strip() for p in paragraphs]
            if sum(self.tokenizer.count(p) for p in paragraphs) > target:
                raise ValueError("Summary exceeded output budget; use a more concise summarizer or larger budget")
            summary_blocks = []
            # Split overlong summary paragraphs to respect the embedding limit.
            for paragraph in paragraphs:
                for start, end in chunk_spans(paragraph, self.config.embedding_limit, 0, self.tokenizer):
                    summary_blocks.append(Block("%s:b%d" % (node_id, len(summary_blocks)), paragraph[start:end],
                                                source_block_ids=[b.id for b in blocks]))
            node = Node(node_id, kind, 1 + max(n.level for n in children),
                        children[0].start, children[-1].end, section_id,
                        summary_blocks, [n.id for n in children])
            nodes[node.id] = node
            for child in children:
                child.parent = node.id
            return node

        async def reduce_to_one(frontier, kind, section_id):
            # Always create a chapter/root container, even for one source leaf.
            while True:
                grouped = groups(frontier)
                final = len(grouped) == 1
                jobs = [(new_id(), group) for group in grouped]
                frontier = list(await asyncio.gather(*(
                    parent(node_id, group, kind if final else "summary", section_id)
                    for node_id, group in jobs)))
                if final:
                    return frontier[0]

        # Section jobs are independent; IDs for leaves are allocated first in
        # source order. Summary IDs remain stable for a fixed scheduling order.
        leaves_by_section = []
        for section in sections:
            leaves = []
            for start, end in chunk_spans(text[section.start:section.end], self.config.chunk_size,
                                          self.config.chunk_overlap, self.tokenizer):
                node_id = new_id()
                start, end = start + section.start, end + section.start
                node = Node(node_id, "leaf", 0, start, end, section.id,
                            [Block(node_id + ":b0", text[start:end])])
                nodes[node.id] = node
                leaves.append(node)
            leaves_by_section.append(leaves)
        chapters = list(await asyncio.gather(*(
            reduce_to_one(leaves, "chapter", section.id)
            for section, leaves in zip(sections, leaves_by_section))))
        root = await reduce_to_one(chapters, "root", None)
        all_blocks = [b for node in sorted(nodes.values(), key=lambda n: n.id) for b in node.blocks]

        async def embed_batch(batch):
            async with gate:
                vectors = await self.embedder.embed([b.text for b in batch])
            if len(vectors) != len(batch):
                raise ValueError("Embedding count mismatch")
            for block, vector in zip(batch, vectors):
                block.embedding = vector
        size = self.config.embedding_batch
        await asyncio.gather(*(embed_batch(all_blocks[i:i + size]) for i in range(0, len(all_blocks), size)))
        index = TreeIndex(hashlib.sha256(text.encode()).hexdigest(), source_name, text, root.id,
                          nodes, sections, {
                              "embedder": self.embedder.name,
                              "summarizer": getattr(self.summarizer, "name", type(self.summarizer).__name__),
                              "tokenizer": getattr(self.tokenizer, "name", type(self.tokenizer).__name__),
                              "config": asdict(self.config)})
        index.validate()
        return index
