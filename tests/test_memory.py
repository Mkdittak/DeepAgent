import asyncio
import os
import tempfile

from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent.core import create_agent


def last_ai_text(result):
    msgs = result.get("messages", [])
    for m in reversed(msgs):
        content = getattr(m, "content", "")
        if getattr(m, "type", "") == "ai" and content:
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return content
    return ""


async def ask(db_path, thread_id, message):
    async with AsyncSqliteSaver.from_conn_string(db_path) as cp:
        agent = create_agent(checkpointer=cp)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"recursion_limit": 30, "configurable": {"thread_id": thread_id}},
        )
        return last_ai_text(result)


async def main():
    db = os.path.join(tempfile.mkdtemp(), "checkpoints.sqlite")
    T = "thread-abc"

    print("Turn 1 (state a fact):")
    r1 = await ask(db, T, "Remember this: my favorite color is teal. Reply with just 'noted'.")
    print("  ->", r1.strip()[:120])

    print("Turn 5 (recall, same thread, several turns later):")
    for filler in ["What is 2+2? One word.", "Name a fruit. One word.", "Say hi. One word."]:
        await ask(db, T, filler)
    r5 = await ask(db, T, "What did I say my favorite color is? Answer with just the color.")
    print("  ->", r5.strip()[:120])
    print("  RECALL PASS:", "teal" in r5.lower())

    print("Restart persistence (fresh saver + agent on same DB file):")
    r_restart = await ask(db, T, "Again: what is my favorite color? Just the color.")
    print("  ->", r_restart.strip()[:120])
    print("  PERSIST PASS:", "teal" in r_restart.lower())

    print("Isolation (different thread must NOT know):")
    r_other = await ask(db, "thread-xyz", "What is my favorite color? If you don't know, say 'unknown'.")
    print("  ->", r_other.strip()[:120])
    print("  ISOLATION PASS:", "teal" not in r_other.lower())


asyncio.run(main())
