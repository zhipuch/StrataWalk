import json
import unittest
from stratawalk import BuildConfig, IndexBuilder
from stratawalk.models import Block
from stratawalk.providers.compatible import LLMSummarizer
from stratawalk.providers.offline import HashEmbedder
from stratawalk.tokenization import ByteTokenizer


class Responses:
    name = "summary-fixture"
    def __init__(self, responses):
        self.responses, self.messages = iter(responses), []
    async def complete(self, messages, *, max_tokens):
        self.messages.append((messages, max_tokens))
        return next(self.responses)


class SummaryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlong_output_is_corrected_not_truncated(self):
        model = Responses([json.dumps({"blocks": ["x" * 101]}), json.dumps({"blocks": ["Core idea."]})])
        result = await LLMSummarizer(model).summarize([Block("b0", "original")], 100, topic_size=50, max_topics=2)
        self.assertEqual(result, ["Core idea."])
        self.assertEqual(len(model.messages), 2)
        self.assertIn("Previous response was invalid", model.messages[-1][0][0]["content"])
        self.assertIn("output budget", model.messages[-1][0][0]["content"])
        self.assertNotIn("x" * 101, model.messages[-1][0][0]["content"])

    async def test_topic_count_and_individual_length_are_enforced(self):
        for paragraphs, error in [(["a", "b", "c"], "too many topics"), (["x" * 51], "individual budget")]:
            model = Responses([json.dumps({"blocks": paragraphs})] * 2)
            with self.assertRaisesRegex(ValueError, error):
                await LLMSummarizer(model).summarize([Block("b0", "source")], 100,
                                                     max_topics=2, topic_size=50, attempts=2)
            self.assertEqual(len(model.messages), 2)

    async def test_malformed_json_retry_and_exhaustion(self):
        model = Responses(["not json", '{"blocks":["Concise topic."]}'])
        result = await LLMSummarizer(model).summarize([Block("b0", "source")], 100)
        self.assertEqual(result, ["Concise topic."])
        model = Responses(['{"blocks":[]}'] * 2)
        with self.assertRaisesRegex(ValueError, "after 2 attempts"):
            await LLMSummarizer(model).summarize([Block("b0", "source")], 100, attempts=2)

    async def test_full_request_budget_checked_before_model_call(self):
        model = Responses([])
        with self.assertRaisesRegex(ValueError, "context budget"):
            await LLMSummarizer(model).summarize([Block("b0", '"\\\n' * 1000)], 100, context_limit=2000)
        self.assertEqual(model.messages, [])

    async def test_runtime_request_overhead_can_split_a_planned_group(self):
        class SmallEnvelope(LLMSummarizer):
            calls = []
            def fits(self, blocks, budget, **kwargs):
                return len(blocks) <= 2
            async def summarize(self, blocks, budget, **kwargs):
                self.calls.append(len(blocks))
                return ["s" * min(16, budget)]
        summarizer = SmallEnvelope(Responses([]))
        config = BuildConfig(chunk_size=32, chunk_overlap=0, summary_size=16,
                             max_children=4, reduction_input=128)
        index = await IndexBuilder(summarizer, HashEmbedder(), config=config).build("a" * 256)
        index.validate()
        self.assertTrue(summarizer.calls)
        self.assertLessEqual(max(summarizer.calls), 2)

    def test_prompt_encodes_abstraction_and_fidelity_rules(self):
        instructions = LLMSummarizer.messages([Block("b0", "正文")], 100, 3, 40, "utf8-bytes")[0]["content"]
        for phrase in ("most important points or topics", "deduplicate overlap", "negations",
                       "uncertainty", "disagreements", "source language", "first-occurrence order",
                       "1..3 topics", "100 utf8-bytes", "40 utf8-bytes", "untrusted DATA"):
            self.assertIn(phrase, instructions)
