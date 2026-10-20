"""Ordered, dependency-driven reduction: each parent waits only for its children."""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
from ..models import Block, Node, Section, TreeIndex
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
    max_topics: int = 6
    topic_size: int = 256
    summary_retries: int = 2
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
        if self.max_children < 2 or min(self.concurrency, self.embedding_batch, self.summary_size,
                                         self.max_topics, self.topic_size) < 1:
            raise ValueError("Invalid grouping, topic or concurrency configuration")
        summary_cap = min(self.summary_size, self.max_topics * min(self.topic_size, self.embedding_limit))
        if 2 * max(self.chunk_size, summary_cap) > self.reduction_input:
            raise ValueError("reduction_input must fit at least two chunks or summaries")
        reserve = LLMSummarizer.completion_limit(summary_cap, self.max_topics)
        if self.reduction_input + reserve + self.safety_margin >= self.context_limit:
            raise ValueError("Context limit leaves no room for prompt/serialization overhead")


@dataclass
class _Pending:
    """A planned subtree and its maximum output size, independent of completion order."""
    future: asyncio.Future
    weight: int


class IndexBuilder:
    def __init__(self, summarizer, embedder, *, config=None, parser=None, tokenizer=None):
        self.summarizer, self.embedder = summarizer, embedder
        self.config = config or BuildConfig()
        self.config.validate()
        self.parser = parser or MarkdownSectionParser()
        self.tokenizer = tokenizer or ByteTokenizer()

    async def build(self, text: str, source_name="document") -> TreeIndex:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Source must be nonempty text")
        sections = self.parser.parse(text)
        # Validate adapters before allocating tasks or making model requests.
        # An empty frontier cannot reduce; invalid spans would corrupt provenance.
        if not isinstance(sections, list) or not sections:
            raise ValueError("Parser must return a nonempty list of sections")
        covered, section_ids = 0, set()
        for section in sections:
            if (not isinstance(section, Section) or not isinstance(section.id, str) or not section.id
                    or section.id in section_ids or not isinstance(section.title, str)
                    or any(not isinstance(v, int) or isinstance(v, bool) for v in (section.start, section.end))
                    or section.start != covered or not section.start < section.end <= len(text)):
                raise ValueError("Parser sections must have unique IDs and cover the source contiguously in order")
            covered = section.end
            section_ids.add(section.id)
        if covered != len(text):
            raise ValueError("Parser sections must cover the full source")
        nodes, tasks = {}, []
        gate = asyncio.Semaphore(self.config.concurrency)
        loop = asyncio.get_running_loop()
        count = 0
        topic_limit = min(self.config.topic_size, self.config.embedding_limit)
        summary_cap = min(self.config.summary_size, self.config.max_topics * topic_limit)

        def new_id():
            nonlocal count
            node_id = "n%06d" % count
            count += 1
            return node_id

        def groups(frontier):
            """Reserve summary caps before outputs exist; never group by readiness order."""
            result, group, used = [], [], 0
            for item in frontier:
                if group and (used + item.weight > self.config.reduction_input or
                              len(group) >= self.config.max_children):
                    result.append(group)
                    group, used = [], 0
                group.append(item)
                used += item.weight
            if group:
                result.append(group)
            if len(frontier) > 1 and len(result) >= len(frontier):
                raise ValueError("Reduction cannot make progress; increase the input budget")
            return result

        def llm_options():
            return dict(max_topics=self.config.max_topics, topic_size=topic_limit,
                        tokenizer=self.tokenizer, attempts=self.config.summary_retries + 1,
                        context_limit=self.config.context_limit, safety_margin=self.config.safety_margin)

        async def parent(node_id, children, kind, section_id):
            blocks = [b for n in children for b in n.blocks]
            input_size = sum(self.tokenizer.count(b.text) for b in blocks)
            target = min(summary_cap, max(1, input_size // 2))
            passthrough = (len(children) == 1 and input_size <= summary_cap and
                           len(blocks) <= self.config.max_topics and
                           all(self.tokenizer.count(b.text) <= topic_limit for b in blocks))
            is_llm = isinstance(self.summarizer, LLMSummarizer)
            if is_llm and not passthrough and not self.summarizer.fits(blocks, target, **llm_options()):
                # Actual JSON identifiers, escaping and prompt text matter. If
                # text-only planning was optimistic, reduce contiguous halves.
                # This changes only this subtree, never waits for a whole level.
                if len(children) < 3:
                    raise ValueError("Even a pair cannot fit the serialized summary request; increase context_limit or lower chunk/summary sizes")
                middle = len(children) // 2
                children = list(await asyncio.gather(
                    parent(new_id(), children[:middle], "summary", section_id),
                    parent(new_id(), children[middle:], "summary", section_id)))
                return await parent(node_id, children, kind, section_id)
            if passthrough:
                paragraphs, target = [b.text for b in blocks], summary_cap
            elif not any(b.text.strip() for b in blocks):
                paragraphs = ["-" if target < 7 else "[blank]"]
            else:
                async with gate:
                    if is_llm:
                        paragraphs = await self.summarizer.summarize(blocks, target, **llm_options())
                    else:
                        paragraphs = await self.summarizer.summarize(blocks, target)
            if not isinstance(paragraphs, list) or not paragraphs or any(
                    not isinstance(p, str) or (not p if passthrough else not p.strip()) for p in paragraphs):
                raise ValueError("Summarizer returned empty/invalid blocks")
            paragraphs = [p if passthrough else p.strip() for p in paragraphs]
            if sum(self.tokenizer.count(p) for p in paragraphs) > target:
                raise ValueError("Summary exceeded output budget")
            if len(paragraphs) > self.config.max_topics:
                raise ValueError("Summary exceeded maximum topic count")
            summary_blocks = []
            for paragraph in paragraphs:
                for start, end in chunk_spans(paragraph, topic_limit, 0, self.tokenizer):
                    summary_blocks.append(Block("%s:b%d" % (node_id, len(summary_blocks)), paragraph[start:end],
                                                source_block_ids=[b.id for b in blocks]))
            if len(summary_blocks) > self.config.max_topics:
                raise ValueError("Summary requires too many topic blocks; lower output length or raise max_topics")
            node = Node(node_id, kind, 1 + max(n.level for n in children),
                        children[0].start, children[-1].end, section_id,
                        summary_blocks, [n.id for n in children])
            nodes[node.id] = node
            for child in children:
                child.parent = node.id
            return node

        def schedule(frontier, kind, section_id):
            """Plan the full local dependency graph without awaiting any level."""
            while True:
                grouped = groups(frontier)
                final = len(grouped) == 1
                following = []
                for group in grouped:
                    node_id = new_id()

                    async def run(dependencies=tuple(group), node_id=node_id,
                                  role=kind if final else "summary"):
                        children = await asyncio.gather(*(item.future for item in dependencies))
                        return await parent(node_id, children, role, section_id)
                    task = asyncio.create_task(run())
                    tasks.append(task)
                    following.append(_Pending(task, summary_cap))
                if final:
                    return following[0]
                frontier = following

        # Allocate all source leaves first. Group membership is determined by
        # source order and reserved budgets, not by which LLM finishes first.
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
                ready = loop.create_future()
                ready.set_result(node)
                leaves.append(_Pending(ready, self.tokenizer.count(node.blocks[0].text)))
            leaves_by_section.append(leaves)
        try:
            chapters = [schedule(leaves, "chapter", section.id)
                        for section, leaves in zip(sections, leaves_by_section)]
            # Root/upper-section tasks are scheduled immediately too, allowing
            # one ready group of chapter nodes to reduce while others still run.
            root = await schedule(chapters, "root", None).future
            all_blocks = [b for node in sorted(nodes.values(), key=lambda n: n.id) for b in node.blocks]

            async def embed_batch(batch):
                async with gate:
                    vectors = await self.embedder.embed([b.text for b in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Embedding count mismatch")
                for block, vector in zip(batch, vectors):
                    block.embedding = vector
            size = self.config.embedding_batch
            embedding_tasks = [asyncio.create_task(embed_batch(all_blocks[i:i + size]))
                               for i in range(0, len(all_blocks), size)]
            tasks.extend(embedding_tasks)
            await asyncio.gather(*embedding_tasks)
            index = TreeIndex(hashlib.sha256(text.encode()).hexdigest(), source_name, text, root.id,
                              nodes, sections, {"embedder": self.embedder.name,
                              "summarizer": getattr(self.summarizer, "name", type(self.summarizer).__name__),
                              "tokenizer": getattr(self.tokenizer, "name", type(self.tokenizer).__name__),
                              "scheduler": "dependency-dag-v1",
                              "summary_prompt": getattr(self.summarizer, "prompt_version", None),
                              "config": asdict(self.config)})
            index.validate()
            return index
        finally:
            # Cancel sibling work on any failed dependency or caller cancellation.
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
