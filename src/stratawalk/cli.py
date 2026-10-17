"""Small CLI: build an index, inspect it, search it, or run a tool-using agent."""
import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from . import BuildConfig, IndexBuilder, load_index, save_index
from .agent import Agent, AgentConfig, ChatPolicy, TreeTools
from .index.search import SemanticSearch
from .parsing import LlamaIndexSectionParser, MarkdownSectionParser
from .providers.compatible import CompatibleChat, CompatibleClient, CompatibleEmbedder, LLMSummarizer
from .providers.offline import ExtractiveSummarizer, HashEmbedder, OfflinePolicy
from .tokenization import ByteTokenizer, TiktokenTokenizer


def parser():
    root = argparse.ArgumentParser(prog="stratawalk", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build an ordered summary tree from UTF-8 Markdown/TXT")
    build.add_argument("document", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--parser", choices=["markdown", "llamaindex"], default="markdown")
    build.add_argument("--heading-level", type=int)
    for name, field in BuildConfig.__dataclass_fields__.items():
        build.add_argument("--" + name.replace("_", "-"), type=int, default=field.default)
    inspect = commands.add_parser("inspect", help="Print index structure/statistics")
    inspect.add_argument("index", type=Path)
    for command in ("search", "ask"):
        sub = commands.add_parser(command, help="Search blocks" if command == "search" else "Run the agent")
        sub.add_argument("index", type=Path)
        sub.add_argument("question")
        if command == "search":
            sub.add_argument("--top-k", type=int, default=5)
            sub.add_argument("--kind", choices=["leaf", "summary", "chapter", "root"])
        else:
            sub.add_argument("--max-steps", type=int, default=24)
            sub.add_argument("--context-limit", type=int, default=24000)
            sub.add_argument("--output-reserve", type=int, default=2048)
            sub.add_argument("--trace", type=Path, help="Write tool trace (contains document excerpts)")
            sub.add_argument("--json", action="store_true", help="Print answer, citations and status as JSON")
    for sub in (build, commands.choices["search"], commands.choices["ask"]):
        sub.add_argument("--provider", choices=["offline", "compatible"], default="offline")
        sub.add_argument("--base-url", default=os.environ.get("STRATAWALK_BASE_URL"))
        sub.add_argument("--chat-model", default=os.environ.get("STRATAWALK_CHAT_MODEL"))
        sub.add_argument("--embedding-model", default=os.environ.get("STRATAWALK_EMBEDDING_MODEL"))
        sub.add_argument("--encoding", help="Optional tiktoken encoding; default uses UTF-8 byte budgets")
    return root


def providers(args, tokenizer):
    if args.provider == "offline":
        return HashEmbedder(), ExtractiveSummarizer(tokenizer), OfflinePolicy()
    if not args.base_url or not args.embedding_model:
        raise ValueError("Compatible provider requires --base-url and --embedding-model (or STRATAWALK_* env vars)")
    client = CompatibleClient(args.base_url, os.environ.get("STRATAWALK_API_KEY", ""))
    embedder = CompatibleEmbedder(client, args.embedding_model)
    if args.command == "search":
        return embedder, None, None
    if not args.chat_model:
        raise ValueError("Compatible build/ask requires --chat-model")
    model = CompatibleChat(client, args.chat_model)
    return embedder, LLMSummarizer(model), ChatPolicy(model, getattr(args, "output_reserve", 2048))


async def run(args):
    if args.command == "inspect":
        index = load_index(args.index)
        print(json.dumps({"document_id": index.document_id, "source": index.source_name,
                          "root_id": index.root_id, "sections": [asdict(s) for s in index.sections],
                          "nodes": len(index.nodes), "blocks": len(index.block_map()),
                          "depth": index.nodes[index.root_id].level,
                          "embedding_dimensions": len(next(iter(index.block_map().values())).embedding),
                          "metadata": index.metadata}, ensure_ascii=False, indent=2))
        return 0
    tokenizer = TiktokenTokenizer(args.encoding) if args.encoding else ByteTokenizer()
    embedder, summarizer, policy = providers(args, tokenizer)
    if args.command == "build":
        if args.document.suffix.lower() not in {".md", ".markdown", ".txt"}:
            raise ValueError("This version accepts UTF-8 .md/.markdown/.txt; convert other formats first")
        config = BuildConfig(**{name: getattr(args, name) for name in BuildConfig.__dataclass_fields__})
        section_parser = LlamaIndexSectionParser() if args.parser == "llamaindex" else MarkdownSectionParser(args.heading_level)
        index = await IndexBuilder(summarizer, embedder, config=config, parser=section_parser,
                                   tokenizer=tokenizer).build(args.document.read_text(encoding="utf-8"), args.document.name)
        save_index(index, args.output)
        print("Saved %s: %d nodes, %d blocks, depth %d" % (
            args.output, len(index.nodes), len(index.block_map()), index.nodes[index.root_id].level))
    else:
        index = load_index(args.index)
        search = SemanticSearch(index, embedder)
        if args.command == "search":
            hits = await search.search(args.question, args.top_k, args.kind)
            print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
        else:
            tools = TreeTools(index, search, tokenizer=tokenizer)
            result = await Agent(tools, policy, tokenizer=tokenizer, config=AgentConfig(
                max_steps=args.max_steps, context_limit=args.context_limit,
                output_reserve=args.output_reserve)).run(args.question)
            if args.trace:
                args.trace.parent.mkdir(parents=True, exist_ok=True)
                args.trace.write_text(json.dumps(result.trace, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.json:
                print(json.dumps({"answer": result.answer, "citations": result.citations, "status": result.status},
                                 ensure_ascii=False, indent=2))
            else:
                print(result.answer)
                print("\nStatus: " + result.status)
                for citation in result.citations:
                    print("[%s] %s characters %d:%d" % (
                        citation["block_id"], citation["source_name"], citation["start"], citation["end"]))
            return 0 if result.status == "complete" else 2
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        print("stratawalk: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
