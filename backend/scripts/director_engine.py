"""Director Engine — single LLM call per round decides actions for all agents.

Instead of invoking one LLM call per agent per round, the Director issues a
single "omniscient" call that returns a JSON array of actions for every active
agent.  This dramatically reduces LLM invocations and allows for coordinated,
narrative-driven behaviour across agents.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Any

from oasis import ActionType, ManualAction

logger = logging.getLogger("social.director")

# ---------------------------------------------------------------------------
# Action-type mapping
# ---------------------------------------------------------------------------
_ACTION_MAP: dict[str, tuple[ActionType, list[str]]] = {
    "create_post": (ActionType.CREATE_POST, ["content"]),
    "like_post": (ActionType.LIKE_POST, ["post_id"]),
    "create_comment": (ActionType.CREATE_COMMENT, ["post_id", "content"]),
    "repost": (ActionType.REPOST, ["post_id"]),
    "follow": (ActionType.FOLLOW, ["followee_id"]),
    "like_comment": (ActionType.LIKE_COMMENT, ["comment_id"]),
}

# Alias: the LLM sometimes uses "user_id" for follow targets
_FOLLOW_ALIAS = "user_id"

# ---------------------------------------------------------------------------
# Director system prompt (Japanese — matches simulation language)
# ---------------------------------------------------------------------------
DIRECTOR_SYSTEM_PROMPT = """\
あなたはSNSシミュレーションの演出家（Director）です。
各エージェントのペルソナと現在のプラットフォーム状態を元に、
全エージェントが次にとるリアルなソーシャルメディア行動を決定してください。

ルール:
- 各エージェントのペルソナ（職業・立場・性格）に忠実な行動を選んでください
- 全員がアクションする必要はありません。活動しないエージェントは省略してください
- 投稿やコメントの内容は、そのエージェントの立場から自然な日本語で具体的に書いてください
- いいね・フォローだけでなく、積極的に投稿やコメントも生成してください
- エージェント間の議論や反応の連鎖を意識してください

出力はJSON配列のみ。他のテキストは不要です。
"""


def get_platform_state(
    db_path: str,
    agent_names: dict[int, str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Query SQLite for recent posts with engagement counts.

    Args:
        db_path: Path to the platform SQLite database.
        agent_names: Mapping of ``user_id`` to display name.
        limit: Maximum number of posts to return.

    Returns:
        A list of dicts, each representing a recent post with metadata.
    """
    query = """
        SELECT p.post_id, p.user_id, p.content, p.created_at,
               (SELECT COUNT(*) FROM "like" WHERE post_id = p.post_id) AS likes,
               (SELECT COUNT(*) FROM comment WHERE post_id = p.post_id) AS comments
        FROM post p
        ORDER BY p.created_at DESC
        LIMIT ?
    """

    posts: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, (limit,))
        for row in cursor:
            posts.append({
                "post_id": row["post_id"],
                "author": agent_names.get(row["user_id"], f"user_{row['user_id']}"),
                "content": (row["content"] or "")[:200],
                "created_at": row["created_at"],
                "likes": row["likes"],
                "comments": row["comments"],
            })
        conn.close()
    except Exception:
        logger.exception("Failed to query platform state from %s", db_path)

    return posts


class DirectorEngine:
    """Orchestrates a single LLM call per round to decide all agent actions.

    Args:
        model: A camel ``ModelBackend`` instance (from ``ModelFactory.create()``).
            Retained for reference / future use, but the engine calls the OpenAI
            SDK directly to avoid ChatAgent tool-calling overhead.
        agent_personas: ``{agent_id: {"name": str, "profile": str}}``.
        platform_type: ``"twitter"`` or ``"reddit"``.
    """

    def __init__(
        self,
        model: Any,
        agent_personas: dict[int, dict[str, str]],
        platform_type: str,
    ) -> None:
        self.model = model
        self.agent_personas = agent_personas
        self.platform_type = platform_type

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def decide_actions(
        self,
        env: Any,
        active_agents: list[int],
        db_path: str,
        round_num: int,
        total_rounds: int,
        simulated_hour: int,
    ) -> dict[Any, list[ManualAction]]:
        """Run the Director for a single round.

        Args:
            env: The OASIS social environment.
            active_agents: Agent IDs that should participate this round.
            db_path: Path to the platform SQLite database.
            round_num: Current round number (1-indexed).
            total_rounds: Total number of rounds in the simulation.
            simulated_hour: The simulated hour of day (0-23).

        Returns:
            A dict mapping ``SocialAgent`` instances to their
            ``list[ManualAction]``.  Returns an empty dict on failure.
        """
        try:
            return await self._decide_actions_inner(
                env, active_agents, db_path, round_num, total_rounds, simulated_hour
            )
        except Exception:
            logger.exception(
                "Director engine failed on round %d — skipping round", round_num
            )
            return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _decide_actions_inner(
        self,
        env: Any,
        active_agents: list[int],
        db_path: str,
        round_num: int,
        total_rounds: int,
        simulated_hour: int,
    ) -> dict[Any, list[ManualAction]]:
        # 1. Build name lookup for active agents
        agent_names: dict[int, str] = {
            aid: self.agent_personas[aid]["name"]
            for aid in active_agents
            if aid in self.agent_personas
        }

        # 2. Get platform state
        posts = get_platform_state(db_path, agent_names)

        # 3. Build prompts
        user_prompt = self._build_user_prompt(
            active_agents, posts, round_num, total_rounds, simulated_hour
        )

        # 4. Call LLM via OpenAI SDK
        raw_text = self._call_llm(user_prompt)
        if not raw_text:
            logger.warning("Director received empty LLM response on round %d", round_num)
            return {}

        # 5. Parse JSON from response
        actions_data = self._parse_response(raw_text)
        if not actions_data:
            logger.warning(
                "Director could not parse actions on round %d — raw: %.300s",
                round_num,
                raw_text,
            )
            return {}

        # 6. Convert to ManualAction objects
        return self._build_manual_actions(actions_data, env)

    def _build_user_prompt(
        self,
        active_agents: list[int],
        posts: list[dict[str, Any]],
        round_num: int,
        total_rounds: int,
        simulated_hour: int,
    ) -> str:
        """Assemble the user prompt sent to the Director LLM."""
        sections: list[str] = []

        # -- Personas --
        sections.append("## アクティブなエージェント\n")
        for aid in active_agents:
            persona = self.agent_personas.get(aid)
            if persona is None:
                continue
            sections.append(
                f"- **ID {aid}** — {persona['name']}: {persona['profile']}"
            )

        # -- Platform state --
        sections.append("\n## 現在のタイムライン（最新の投稿）\n")
        if posts:
            for p in posts:
                sections.append(
                    f"- [post_id={p['post_id']}] {p['author']}: "
                    f"{p['content']!r}  (♥{p['likes']}  💬{p['comments']})"
                )
        else:
            sections.append("（まだ投稿はありません）")

        # -- Round context --
        sections.append(
            f"\n## ラウンド情報\n"
            f"- ラウンド: {round_num}/{total_rounds}\n"
            f"- シミュレーション時刻: {simulated_hour}:00\n"
            f"- プラットフォーム: {self.platform_type}"
        )

        # -- Output format instructions --
        sections.append(
            "\n## 出力フォーマット\n"
            "JSON配列で各エージェントのアクションを返してください。例:\n"
            "```json\n"
            "[\n"
            '  {"agent_id": 1, "action": "create_post", "content": "投稿内容..."},\n'
            '  {"agent_id": 2, "action": "like_post", "post_id": 5},\n'
            '  {"agent_id": 3, "action": "create_comment", "post_id": 5, '
            '"content": "コメント内容..."},\n'
            '  {"agent_id": 1, "action": "repost", "post_id": 3},\n'
            '  {"agent_id": 4, "action": "follow", "user_id": 2},\n'
            '  {"agent_id": 2, "action": "like_comment", "comment_id": 10}\n'
            "]\n"
            "```\n"
            "各エージェントは0個以上のアクションを持てます。"
        )

        return "\n".join(sections)

    def _call_llm(self, user_prompt: str) -> str:
        """Call the LLM using the OpenAI SDK directly.

        We bypass camel's ChatAgent to avoid tool-calling overhead.
        The proxy at ``OPENAI_API_BASE_URL`` accepts OpenAI-compatible requests.
        """
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
            base_url=os.environ.get("OPENAI_API_BASE_URL"),
        )

        response = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL_NAME", "claude-code"),
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )

        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_response(raw: str) -> list[dict[str, Any]] | None:
        """Extract a JSON array from the LLM response.

        Handles responses wrapped in markdown code fences and leading/trailing
        whitespace.  Returns ``None`` if parsing fails.
        """
        text = raw.strip()

        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Last-ditch: try to find the outermost [ ... ]
            bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket_match:
                try:
                    data = json.loads(bracket_match.group(0))
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON even after bracket extraction")
                    return None
            else:
                logger.warning("No JSON array found in Director response")
                return None

        if not isinstance(data, list):
            logger.warning("Director response JSON is not an array: %s", type(data))
            return None

        return data

    def _build_manual_actions(
        self,
        actions_data: list[dict[str, Any]],
        env: Any,
    ) -> dict[Any, list[ManualAction]]:
        """Convert parsed action dicts into ``ManualAction`` objects.

        Returns a mapping from ``SocialAgent`` to their actions.
        """
        result: dict[Any, list[ManualAction]] = {}

        for act in actions_data:
            agent_id = act.get("agent_id")
            action_name = act.get("action")

            if agent_id is None or action_name is None:
                logger.warning("Skipping action with missing agent_id or action: %s", act)
                continue

            # Resolve agent object from the environment graph
            try:
                agent = env.agent_graph.get_agent(agent_id)
            except Exception:
                logger.warning(
                    "Agent ID %s not found in agent graph — skipping action", agent_id
                )
                continue

            if agent is None:
                logger.warning(
                    "Agent ID %s returned None from agent graph — skipping", agent_id
                )
                continue

            # Look up action type
            mapping = _ACTION_MAP.get(action_name)
            if mapping is None:
                logger.warning("Unknown action type %r — skipping", action_name)
                continue

            action_type, required_keys = mapping

            # Build action_args
            action_args: dict[str, Any] = {}
            for key in required_keys:
                value = act.get(key)
                # Handle follow alias: LLM may use "user_id" instead of "followee_id"
                if value is None and key == "followee_id":
                    value = act.get(_FOLLOW_ALIAS)
                if value is None:
                    logger.warning(
                        "Action %r for agent %s missing required key %r — skipping",
                        action_name,
                        agent_id,
                        key,
                    )
                    break
                action_args[key] = value
            else:
                # All required keys present — create the ManualAction
                manual_action = ManualAction(
                    action_type=action_type,
                    action_args=action_args,
                )
                result.setdefault(agent, []).append(manual_action)

        logger.info(
            "Director produced actions for %d agent(s), %d action(s) total",
            len(result),
            sum(len(v) for v in result.values()),
        )
        return result
