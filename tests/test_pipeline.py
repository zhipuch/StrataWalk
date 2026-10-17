"""Event-driven scheduling regressions: no wall-clock performance assertions."""
import asyncio
import unittest
from stratawalk import BuildConfig, IndexBuilder
from stratawalk.models import Section
from stratawalk.providers.offline import ExtractiveSummarizer, HashEmbedder
from stratawalk.tokenization import ByteTokenizer


def config():
    return BuildConfig(chunk_size=32, chunk_overlap=0, embedding_limit=64,
                       summary_size=16, reduction_input=128, max_children=2, concurrency=4)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_parent_does_not_wait_for_unrelated_same_level_group(self):
        parent_started, slow_started = asyncio.Event(), asyncio.Event()
        events = []
        class Observed:
            async def summarize(self, blocks, budget):
                ids = {b.id.split(":")[0] for b in blocks}
                if "n000004" in ids:
                    slow_started.set()
                    await parent_started.wait()
                    events.append("slow_finished")
                if ids == {"n000008", "n000009"}:
                    await slow_started.wait()
                    events.append("parent_started")
                    parent_started.set()
                return ["s" * min(16, budget)]
        index = await asyncio.wait_for(IndexBuilder(Observed(), HashEmbedder(), config=config()).build("a" * 256), 2)
        index.validate()
        self.assertLess(events.index("parent_started"), events.index("slow_finished"))

    async def test_upper_groups_start_before_all_chapters_finish(self):
        upper_started = asyncio.Event()
        events = []
        class FourSections:
            def parse(self, text):
                return [Section("s%d" % i, "Chapter %d" % i, i * 128, (i + 1) * 128) for i in range(4)]
        class Observed:
            async def summarize(self, blocks, budget):
                ids = {b.id.split(":")[0] for b in blocks}
                if "n000008" in ids:
                    await upper_started.wait()
                    events.append("slow_chapter_progress")
                if ids == {"n000018", "n000021"}:
                    events.append("upper_group_started")
                    upper_started.set()
                return ["s" * min(16, budget)]
        index = await asyncio.wait_for(IndexBuilder(Observed(), HashEmbedder(), config=config(),
                                                   parser=FourSections()).build("a" * 512), 2)
        index.validate()
        self.assertLess(events.index("upper_group_started"), events.index("slow_chapter_progress"))

    async def test_failed_group_cancels_sibling_work(self):
        started, never = asyncio.Event(), asyncio.Event()
        active = []
        class Failure:
            async def summarize(self, blocks, budget):
                if blocks[0].id == "n000000:b0":
                    await started.wait()
                    raise ValueError("intentional failure")
                active.append(1)
                started.set()
                try:
                    await never.wait()
                finally:
                    active.pop()
        with self.assertRaisesRegex(ValueError, "intentional failure"):
            await asyncio.wait_for(IndexBuilder(Failure(), HashEmbedder(), config=config()).build("a" * 256), 2)
        self.assertEqual(active, [])
