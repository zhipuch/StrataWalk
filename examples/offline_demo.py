"""Run with: PYTHONPATH=src python3 examples/offline_demo.py"""
import asyncio
from pathlib import Path
from stratawalk import BuildConfig, IndexBuilder, save_index
from stratawalk.agent import Agent, TreeTools
from stratawalk.index.search import SemanticSearch
from stratawalk.providers.offline import ExtractiveSummarizer, HashEmbedder, OfflinePolicy
from stratawalk.tokenization import ByteTokenizer
from stratawalk.presentation import format_index_tree


async def main():
    document = Path(__file__).with_name("report.md")
    tokenizer, embedder = ByteTokenizer(), HashEmbedder()
    index = await IndexBuilder(ExtractiveSummarizer(tokenizer), embedder, tokenizer=tokenizer,
                               config=BuildConfig(chunk_size=768, chunk_overlap=96, summary_size=256,
                                                  reduction_input=2048)).build(document.read_text(encoding="utf-8"), document.name)
    save_index(index, ".stratawalk/example.json")
    print(format_index_tree(index, max_nodes=12))
    print("\nSaved index: .stratawalk/example.json")
    question = "What improved answer quality and required additional memory?"
    print("\nQuestion: " + question)
    tools = TreeTools(index, SemanticSearch(index, embedder), tokenizer=tokenizer)
    result = await Agent(tools, OfflinePolicy(), tokenizer=tokenizer).run(question)
    print(result.answer)
    print("\nSource citations:", [(c["source_name"], c["start"], c["end"]) for c in result.citations])
    print("Trace:", [event["tool"] for event in result.trace])
    print("Status:", result.status, "· offline source excerpts")
    print("Next: inspect your index with PYTHONPATH=src python3 -m stratawalk inspect .stratawalk/example.json --tree")


if __name__ == "__main__":
    asyncio.run(main())
