import unittest

from stratawalk.presentation import format_index_tree
from test_index import builder


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_tree_preserves_order_and_escapes_control_characters(self):
        text = "# Report\n## 第一节\nOriginal evidence.\n## Second\n\x1b[31mText."
        index = await builder().build(text, "source\x1b[31m.md")
        before = index.source_text
        tree = format_index_tree(index, max_nodes=len(index.nodes))
        self.assertLess(tree.index("第一节"), tree.index("Section: \"Second\""))
        for node_id in index.nodes:
            self.assertEqual(tree.count("[" + node_id + " ·"), 1)
        self.assertNotIn("\x1b", tree)
        self.assertIn("\\u001b", tree)
        self.assertEqual(index.source_text, before)
        self.assertNotIn("nodes omitted", tree)
