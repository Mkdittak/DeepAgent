"""
Core Deep Agent setup — one general-purpose agent with broad capabilities.
"""

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware import SkillsMiddleware
from langchain.agents.middleware import TodoListMiddleware

from agent.skills import BUILTIN_SOURCE, SKILLS_SYSTEM_PROMPT
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
- After planning, check the Available Skills list in this prompt: if a skill matches
  the task, your NEXT tool call must be read_file on that skill's SKILL.md
  (limit=1000), and you follow its workflow — including reading any references/
  files the skill tells you to read. Skill file reads (read_file on /skills/...)
  are required, never count as research, and are exempt from the speed and
  repetition rules below.
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
    # StateBackend (the deepagents default) is passed explicitly so the same
    # instance serves both the filesystem tools and SkillsMiddleware. It keeps
    # the FS virtual and `execute` hard-erroring — which is what makes the
    # skills integration instruction-only (see agent/skills.py).
    backend = StateBackend()
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
        backend=backend,
        middleware=[
            # Agent Skills (agentskills.io): discovers /skills/built-in/* from
            # the seeded `files` state (temporal/activities.py seeds it each
            # run) and injects name+description per model call. Constructed
            # directly instead of via the `skills=` param so the prompt
            # template can be the instruction-only variant.
            # Source order = priority (last wins on a name collision):
            # user overrides org overrides built-in, mirroring the memory
            # tiers. Empty sources are harmless — ls() just returns nothing.
            SkillsMiddleware(
                backend=backend,
                sources=[
                    (BUILTIN_SOURCE, "Built-in"),
                    ("/skills/org", "Organization"),
                    ("/skills/user", "Your"),
                ],
                system_prompt=SKILLS_SYSTEM_PROMPT,
            ),
            # deepagents 0.7.8 no longer wires TodoListMiddleware
            # automatically, so add it explicitly — this provides the
            # `write_todos` tool that drives plan.snapshot / PlanBlock
            # (headline of Mandate 1).
            TodoListMiddleware(),
        ],
        # Other built-ins (filesystem, execute, task) are still included by
        # Deep Agents automatically.
    )
