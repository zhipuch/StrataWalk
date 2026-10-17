"""Run with: PYTHONPATH=src python3 examples/offline_demo.py"""
import asyncio
from pathlib import Path
from stratawalk import BuildConfig, IndexBuilder, save_index
from stratawalk.agent import Agent, TreeTools
from stratawalk.index.search import SemanticSearch
from stratawalk.providers.offline import ExtractiveSummarizer, HashEmbedder, OfflinePolicy
from stratawalk.tokenization import ByteTokenizer


async def main():
    document = Path(__file__).with_name("report.md")
    tokenizer, embedder = ByteTokenizer(), HashEmbedder()
    index = await IndexBuilder(ExtractiveSummarizer(tokenizer), embedder, tokenizer=tokenizer,
                               config=BuildConfig(chunk_size=320, chunk_overlap=48, summary_size=160,
                                                  reduction_input=1024)).build(document.read_text(), document.name)
    save_index(index, ".stratawalk/example.json")
    tools = TreeTools(index, SemanticSearch(index, embedder), tokenizer=tokenizer)
    result = await Agent(tools, OfflinePolicy(), tokenizer=tokenizer).run(
        "What improved answer quality and required additional memory?")
    print(result.answer)
    print("\nSource citations:", [(c["source_name"], c["start"], c["end"]) for c in result.citations])
    print("Trace:", [event["tool"] for event in result.trace])


if __name__ == "__main__":
    asyncio.run(main())
