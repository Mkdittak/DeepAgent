"""
Core Deep Agent setup — one general-purpose agent with broad capabilities.
"""

from deepagents import create_deep_agent

from agent.tools import web_search, generate_pptx, generate_xlsx, generate_html

SYSTEM_PROMPT = """\
You are a general-purpose autonomous agent. You can handle ANY user request:
research topics, write code, create presentations, build spreadsheets, generate
landing pages, and more.

CRITICAL RULES — follow these strictly:
- Be FAST. Do NOT over-research. 1-2 web searches max per task. Get info, then produce output.
- NEVER loop. NEVER call the same tool twice with the same or similar arguments.
- NEVER call web_search more than 3 times total in a single task.
- For complex tasks, use write_todos ONCE to outline 3-5 steps max, then execute immediately.
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
        model="google_genai:gemini-3.5-flash",
        system_prompt=SYSTEM_PROMPT,
        tools=[
            web_search,
            generate_pptx,
            generate_xlsx,
            generate_html,
        ],
        checkpointer=checkpointer,
        # Built-in tools (write_todos, filesystem, execute, task) are included
        # automatically by Deep Agents.
    )
