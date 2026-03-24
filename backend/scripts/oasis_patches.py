"""
Monkey-patches for the OASIS social simulation package.

These patches improve simulation quality without modifying the OASIS source
code.  Call ``apply_all_patches()`` once before creating any environments or
running simulations.

Patches included:
  - patch_action_prompt: injects persona into the LLM prompt and allows
    multi-action responses; also fixes a logging bug where the original
    ``return`` was inside the for-loop.
  - patch_environment_template: replaces the default env_template so agents
    are encouraged to take diverse, multi-action steps.

Utility helpers:
  - enable_memory_management: turns on tool-call pruning for every agent.
  - reset_agent_memories: clears conversational memory (keeps system message).
"""

from __future__ import annotations

import logging
from string import Template

from camel.messages import BaseMessage

from oasis.social_agent.agent import ALL_SOCIAL_ACTIONS, SocialAgent
from oasis.social_agent.agent_environment import SocialEnvironment

agent_log = logging.getLogger("social.agent")


# ---------------------------------------------------------------------------
# Patch 1 – action prompt
# ---------------------------------------------------------------------------

async def _patched_perform_action_by_llm(self):
    """Replacement for ``SocialAgent.perform_action_by_llm``.

    Improvements over the original:
      * Prepends the agent's persona (name + user_profile) to the user
        message so the LLM stays in character.
      * Instructs the LLM that it *may* perform multiple actions in one
        turn (e.g. like AND create a post).
      * Fixes the logging loop: ``return response`` is placed *after* the
        for-loop so that every tool_call is logged before returning.
    """
    # Build the environment description
    env_prompt = await self.env.to_text_prompt()

    # Extract persona information from user_info
    name = self.user_info.name
    user_profile = (
        self.user_info.profile
        .get("other_info", {})
        .get("user_profile", "")
    )
    persona_prefix = (
        f"Remember: you are {name}. Your profile: {user_profile}. "
    )

    user_msg = BaseMessage.make_user_message(
        role_name="User",
        content=(
            f"{persona_prefix}"
            f"Please perform social media actions after observing the "
            f"platform environments. Notice that don't limit your "
            f"actions for example to just like the posts. "
            f"You may perform multiple actions if appropriate "
            f"(e.g., like a post AND create a new post, or comment AND "
            f"follow a user). "
            f"Here is your social media environment: {env_prompt}"
        ),
    )

    try:
        agent_log.info(
            f"Agent {self.social_agent_id} observing environment: "
            f"{env_prompt}"
        )
        response = await self.astep(user_msg)

        # Log every tool call (the original returned inside this loop,
        # which caused it to exit after the first tool_call was logged).
        for tool_call in response.info["tool_calls"]:
            action_name = tool_call.tool_name
            args = tool_call.args
            agent_log.info(
                f"Agent {self.social_agent_id} performed "
                f"action: {action_name} with args: {args}"
            )
            if action_name not in ALL_SOCIAL_ACTIONS:
                agent_log.info(
                    f"Agent {self.social_agent_id} get the result: "
                    f"{tool_call.result}"
                )

        # Return *after* all tool calls have been logged.
        return response

    except Exception as e:
        agent_log.error(f"Agent {self.social_agent_id} error: {e}")
        return e


def patch_action_prompt() -> None:
    """Replace ``SocialAgent.perform_action_by_llm`` with the patched version."""
    SocialAgent.perform_action_by_llm = _patched_perform_action_by_llm
    agent_log.info("patch_action_prompt applied")


# ---------------------------------------------------------------------------
# Patch 2 – environment template
# ---------------------------------------------------------------------------

_PATCHED_ENV_TEMPLATE = Template(
    "$groups_env\n"
    "$posts_env\n"
    "Choose actions that best reflect your current inclination based on "
    "your profile and posts content. You may perform multiple actions. "
    "Do not limit your action to just `like` posts."
)


def patch_environment_template() -> None:
    """Replace ``SocialEnvironment.env_template`` with an improved template."""
    SocialEnvironment.env_template = _PATCHED_ENV_TEMPLATE
    agent_log.info("patch_environment_template applied")


# ---------------------------------------------------------------------------
# Apply all patches at once
# ---------------------------------------------------------------------------

def apply_all_patches() -> None:
    """Convenience function — call once before creating environments."""
    patch_action_prompt()
    patch_environment_template()
    agent_log.info("All OASIS patches applied")


# ---------------------------------------------------------------------------
# Utility helpers (not monkey-patches, but useful at runtime)
# ---------------------------------------------------------------------------

def enable_memory_management(env) -> None:
    """Enable tool-call pruning on every agent in *env*.

    This sets ``prune_tool_calls_from_memory = True`` on each agent
    retrieved from ``env.agent_graph.get_agents()``, which prevents the
    agent's context window from growing unboundedly with raw tool-call
    messages.
    """
    for _agent_id, agent in env.agent_graph.get_agents():
        agent.prune_tool_calls_from_memory = True
    agent_log.info("Memory management enabled for all agents")


def reset_agent_memories(env) -> None:
    """Clear conversational memory for every agent, keeping system messages.

    Calls ``agent.init_messages()`` which resets the memory to just the
    system message.
    """
    for _agent_id, agent in env.agent_graph.get_agents():
        agent.init_messages()
    agent_log.info("Agent memories reset for all agents")
