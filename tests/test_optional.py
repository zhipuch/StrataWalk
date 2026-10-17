"""Optional integration tests run when their extra is installed."""
import importlib.util
from pathlib import Path
import unittest
from stratawalk.parsing import LlamaIndexSectionParser
from test_index import builder


@unittest.skipUnless(importlib.util.find_spec("llama_index") is not None, "LlamaIndex extra not installed")
class LlamaIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_alignment_and_build(self):
        text = (Path(__file__).parents[1] / "examples" / "report.md").read_text()
        sections = LlamaIndexSectionParser().parse(text)
        self.assertEqual("".join(text[s.start:s.end] for s in sections), text)
        instance = builder()
        instance.parser = LlamaIndexSectionParser()
        index = await instance.build(text, "report.md")
        index.validate()
        self.assertEqual(len([n for n in index.nodes.values() if n.kind == "chapter"]), len(sections))
