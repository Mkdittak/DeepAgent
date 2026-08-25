import asyncio
from temporalio.client import Client

WF = "agent-write-a-detailed-300word-adventure-story_2026-08-25_08-22-23"


async def main():
    c = await Client.connect("localhost:7233")
    h = c.get_workflow_handle(WF)
    d = await h.describe()
    print("workflow status:", d.status)
    try:
        res = await asyncio.wait_for(h.result(), timeout=10)
        print("result (first 160):", str(res)[:160])
    except Exception as e:
        print("result pending/err:", type(e).__name__)


asyncio.run(main())
