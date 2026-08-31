"""
Core Deep Agent setup — one general-purpose agent with broad capabilities.
"""

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from agent.tools import web_search, generate_pptx, generate_xlsx, generate_html

SYSTEM_PROMPT = """\
You are a general-purpose autonomous agent. You can handle ANY user request:
research topics, write code, create presentations, build spreadsheets, generate
landing pages, and more.

CRITICAL RULES — follow these strictly:
- ALWAYS plan first: your FIRST tool call on EVERY task must be write_todos with a
  short plan (1-5 steps; a simple task gets a 1-2 step plan). Never skip this, and
  never call any other tool or produce output before the plan exists.
- As you finish each step, update the todo list to mark it completed (and mark the
  next step in_progress). Do this with brief write_todos updates, not commentary.
- Be FAST. Do NOT over-research. 1-2 web searches max per task. Get info, then produce output.
- NEVER loop. NEVER call the same tool twice with the same or similar arguments.
- NEVER call web_search more than 3 times total in a single task.
- Once you have enough info, STOP researching and deliver the final output.
- Keep responses concise. Do not ramble or over-explain.

Tool usage:
- Pick the right tool for each step — don't ask the user which tool to use.
- For presentations: use generate_pptx with a title and slide data.
- For spreadsheets: use generate_xlsx with headers and row data.
- For ANY website, HTML page, or landing page: use generate_html. NEVER use write_file for HTML.
- For research: use web_search sparingly — get what you need and move on.
- Be thorough but concise. Deliver complete, usable output.
"""


def create_agent(checkpointer=None):
    """Create and return the configured Deep Agent.

    Args:
        checkpointer: Optional LangGraph checkpointer. When provided (with a
            thread_id in the invocation config), the agent persists and reloads
            conversation state per thread, giving multi-turn memory.
    """
    return create_deep_agent(
        model="google_genai:gemini-3.6-flash",
        system_prompt=SYSTEM_PROMPT,
        tools=[
            web_search,
            generate_pptx,
            generate_xlsx,
            generate_html,
        ],
        checkpointer=checkpointer,
        # deepagents 0.7.8 no longer wires TodoListMiddleware automatically, so
        # add it explicitly — this is what provides the `write_todos` tool that
        # drives the plan.snapshot events / PlanBlock (headline of Mandate 1).
        middleware=[TodoListMiddleware()],
        # Other built-ins (filesystem, execute, task) are still included by
        # Deep Agents automatically.
    )
