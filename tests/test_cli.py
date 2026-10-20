import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from stratawalk import load_index
from stratawalk.cli import main


class CLITests(unittest.TestCase):
    def test_build_preserves_crlf_source_and_character_offsets(self):
        text = "# 报告\r\n\r\n## 结果\r\nOriginal evidence.\r\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.md"
            target = Path(directory) / "index.json"
            source.write_bytes(text.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["build", str(source), "--output", str(target)]), 0)
            index = load_index(target)
            self.assertEqual(index.source_text, text)
            for node in index.nodes.values():
                if node.kind == "leaf":
                    self.assertEqual(node.blocks[0].text, text[node.start:node.end])
