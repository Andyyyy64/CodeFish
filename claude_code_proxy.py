#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI LLM Proxy — OpenAI-compatible API server powered by Claude Code or Codex CLI.
Use your CLI subscription as an LLM backend for CodeFish / MiroFish.

Features:
    - OpenAI-compatible /v1/chat/completions endpoint
    - Tool/function calling emulation via prompt injection + response parsing
    - Automatic rate-limit detection and wait-until-reset for Claude Code CLI

Usage:
    python claude_code_proxy.py --provider claude [--port 8888]
    python claude_code_proxy.py --provider codex  [--port 8888]

Then set in .env:
    LLM_API_KEY=dummy
    LLM_BASE_URL=http://127.0.0.1:8888/v1
    LLM_MODEL_NAME=claude-code   (or codex)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

try:
    from http.server import ThreadingHTTPServer
except ImportError:
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass


# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

PROVIDERS = {
    "claude": {
        "cmd": ["claude", "-p", "--output-format", "text"],
        "system_flag": "--system-prompt",
        "version_cmd": ["claude", "--version"],
        "model_id": "claude-code",
        "owner": "anthropic",
        "install_url": "https://docs.anthropic.com/en/docs/claude-code",
    },
    "codex": {
        "cmd": ["codex", "exec", "--skip-git-repo-check", "-"],
        "system_flag": None,  # codex exec reads prompt from stdin; system prompt prepended
        "version_cmd": ["codex", "--version"],
        "model_id": "codex",
        "owner": "openai",
        "install_url": "https://github.com/openai/codex",
    },
}

# Active provider (set in main)
_provider = None

# Rate-limit state: shared across threads so concurrent requests also wait
_rate_limit_lock = __import__("threading").Lock()
_rate_limit_until = 0.0  # epoch timestamp until which we must wait


# ---------------------------------------------------------------------------
# Tool-calling emulation
# ---------------------------------------------------------------------------

def build_tool_prompt(tools):
    """Convert OpenAI-format tool schemas into a prompt string.

    Uses the same XML format as camel-ai's generate_tool_prompt / extract_tool_call
    so the response can be parsed back into OpenAI tool_calls.
    """
    tool_prompts = []
    for tool in tools:
        func_info = tool.get("function", tool)
        name = func_info["name"]
        desc = func_info.get("description", "")
        tool_json = json.dumps(func_info, indent=2, ensure_ascii=False)
        tool_prompts.append(
            f"Use the function '{name}' to '{desc}':\n{tool_json}"
        )

    tool_block = "\n\n".join(tool_prompts)

    return (
        f"You have access to the following functions:\n\n"
        f"{tool_block}\n\n"
        f"If you choose to call a function ONLY reply in the following format "
        f"with no prefix or suffix:\n\n"
        f'<function=example_function_name>{{"example_name": "example_value"}}</function>\n\n'
        f"Reminder:\n"
        f"- Function calls MUST follow the specified format, start with <function= and end with </function>\n"
        f"- Required parameters MUST be specified\n"
        f"- You may call multiple functions by putting each on its own line\n"
        f"- Put each function call on its own line\n"
        f"- If there is no function call available, answer the question like normal "
        f"with your current knowledge and do not tell the user about function calls."
    )


def parse_tool_calls(response_text):
    """Parse <function=name>{args}</function> from response text.

    Supports multiple tool calls in a single response (via re.finditer).
    Returns (tool_calls_list, remaining_content) where tool_calls_list is in
    OpenAI format or None if no tool call was found.
    """
    pattern = r"<function=(\w+)>(.*?)</function>"
    matches = list(re.finditer(pattern, response_text, re.DOTALL))

    if not matches:
        return None, response_text

    tool_calls = []
    for i, match in enumerate(matches):
        func_name = match.group(1)
        args_str = match.group(2).strip()
        try:
            # Validate it's proper JSON
            json.loads(args_str)
        except json.JSONDecodeError:
            # Try to salvage: sometimes the model adds extra text
            continue

        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": func_name,
                "arguments": args_str,
            },
        })

    if not tool_calls:
        return None, response_text

    # Remove matched tool call tags from content
    remaining = re.sub(pattern, "", response_text, flags=re.DOTALL).strip()
    return tool_calls, remaining or None


def make_completion_response(content, model, tool_calls=None):
    """Build an OpenAI-compatible ChatCompletion response."""
    message = {"role": "assistant"}

    if tool_calls:
        message["content"] = None
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    else:
        message["content"] = content
        finish_reason = "stop"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


# ---------------------------------------------------------------------------
# Rate-limit detection and wait
# ---------------------------------------------------------------------------

# Patterns to detect rate-limit messages from Claude Code CLI
_RATE_LIMIT_PATTERNS = [
    r"[Yy]ou'?ve hit your limit",
    r"[Rr]ate limit",
    r"[Uu]sage limit",
    r"[Oo]ut of (?:free )?messages",
]

# Pattern to extract reset time like "resets 5am (Asia/Tokyo)" or "resets 5:00 AM"
_RESET_TIME_PATTERN = re.compile(
    r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])?"
    r"(?:\s*\(([A-Za-z/_]+)\))?",
    re.IGNORECASE,
)


def detect_rate_limit(text):
    """Check if text contains a rate-limit message.

    Returns True if rate-limited, False otherwise.
    """
    if not text:
        return False
    for pattern in _RATE_LIMIT_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def parse_reset_time(text):
    """Parse the reset timestamp from a rate-limit message.

    Returns epoch timestamp of the reset time, or None if unparsable.
    Falls back to a default wait of 60 minutes if we detect rate limiting
    but can't parse the exact time.
    """
    match = _RESET_TIME_PATTERN.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    ampm = match.group(3)
    tz_name = match.group(4)

    # Convert 12h to 24h
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0

    # Determine timezone
    try:
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    except (KeyError, Exception):
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If the reset time is in the past, it means tomorrow
    if reset <= now:
        reset += timedelta(days=1)

    return reset.timestamp()


def wait_for_rate_limit_reset(text, cli_name="CLI"):
    """If rate-limited, wait until the reset time.

    Updates global _rate_limit_until so other threads also wait.
    Returns the number of seconds waited, or 0 if not rate-limited.
    """
    global _rate_limit_until

    reset_ts = parse_reset_time(text)
    if reset_ts is None:
        # Can't parse time — default wait 60 minutes
        reset_ts = time.time() + 3600
        print(f"  ⏳ Rate limited but couldn't parse reset time. "
              f"Defaulting to 60 min wait.")

    with _rate_limit_lock:
        _rate_limit_until = max(_rate_limit_until, reset_ts)

    wait_seconds = reset_ts - time.time()
    if wait_seconds <= 0:
        return 0

    reset_dt = datetime.fromtimestamp(reset_ts).strftime("%H:%M:%S")
    print(f"\n  ⏳ {cli_name} rate-limited. Waiting until {reset_dt} "
          f"({wait_seconds:.0f}s) ...")

    time.sleep(wait_seconds + 5)  # +5s buffer
    return wait_seconds


def check_global_rate_limit():
    """Block if another thread already detected a rate limit."""
    with _rate_limit_lock:
        remaining = _rate_limit_until - time.time()
    if remaining > 0:
        reset_dt = datetime.fromtimestamp(_rate_limit_until).strftime("%H:%M:%S")
        print(f"  ⏳ Waiting for rate-limit reset at {reset_dt} "
              f"({remaining:.0f}s remaining) ...")
        time.sleep(remaining + 5)


# ---------------------------------------------------------------------------
# Prompt building and CLI execution
# ---------------------------------------------------------------------------

def build_prompt(messages, response_format=None, tools=None):
    """Convert OpenAI-format messages into a prompt string + optional system prompt.

    If tools are provided, appends tool-calling instructions to the system prompt.
    """
    system_prompt = None
    conversation = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_prompt = content
        else:
            conversation.append((role, content))

    if len(conversation) == 1:
        prompt = conversation[0][1]
    else:
        parts = []
        for role, content in conversation:
            prefix = "User" if role == "user" else "Assistant"
            parts.append(f"{prefix}: {content}")
        prompt = "\n\n".join(parts)

    # Append tool definitions to system prompt
    if tools:
        tool_prompt = build_tool_prompt(tools)
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{tool_prompt}"
        else:
            system_prompt = tool_prompt

    if response_format and response_format.get("type") == "json_object":
        prompt += (
            "\n\nYou must respond with valid JSON only. "
            "No markdown code fences, no explanation, just the JSON object."
        )

    return prompt, system_prompt


def run_cli(prompt, system_prompt=None, max_retries=3):
    """Run the active provider CLI and return (response_text, error).

    Automatically detects rate-limit responses and waits until reset.
    """
    p = _provider
    cli_name = p["cmd"][0]

    for attempt in range(max_retries):
        # Check if we're globally rate-limited before even trying
        check_global_rate_limit()

        cmd = list(p["cmd"])
        full_input = prompt

        if system_prompt:
            if p["system_flag"]:
                cmd.extend([p["system_flag"], system_prompt])
            else:
                full_input = f"[System]: {system_prompt}\n\n{prompt}"

        # For codex exec, use -o to capture the final response to a temp file
        out_file = None
        if p["model_id"] == "codex":
            out_file = tempfile.mktemp(suffix=".txt")
            cmd.extend(["-o", out_file])

        result = subprocess.run(
            cmd,
            input=full_input,
            capture_output=True,
            text=True,
            timeout=600,  # Extended timeout to accommodate rate-limit waits
        )

        # Read response text
        response = ""
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or f"exited with code {result.returncode}"

            # Check if the error is a rate limit
            combined = f"{result.stdout}\n{result.stderr}"
            if detect_rate_limit(combined):
                wait_for_rate_limit_reset(combined, cli_name)
                if out_file and os.path.exists(out_file):
                    os.unlink(out_file)
                print(f"  ↻ Retrying (attempt {attempt + 2}/{max_retries}) ...")
                continue

            if out_file and os.path.exists(out_file):
                os.unlink(out_file)
            return None, error_msg

        # Read successful response
        if out_file:
            try:
                with open(out_file, "r") as f:
                    response = f.read().strip()
            except FileNotFoundError:
                response = result.stdout.strip()
            finally:
                if os.path.exists(out_file):
                    os.unlink(out_file)
        else:
            response = result.stdout.strip()

        # Check if the "successful" response is actually a rate-limit message
        if detect_rate_limit(response):
            wait_for_rate_limit_reset(response, cli_name)
            print(f"  ↻ Retrying (attempt {attempt + 2}/{max_retries}) ...")
            continue

        return response, None

    return None, f"Rate limit: max retries ({max_retries}) exhausted"


def check_provider(provider_cfg):
    """Verify that the provider CLI is available."""
    name = provider_cfg["cmd"][0]
    try:
        result = subprocess.run(
            provider_cfg["version_cmd"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
        print(f"  Found: {name} {version}")
        return True
    except FileNotFoundError:
        print(f"  ERROR: '{name}' command not found.")
        print(f"  Install: {provider_cfg['install_url']}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  WARNING: '{name} --version' timed out, proceeding anyway.")
        return True


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {format % args}")

    def _send_json(self, status, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip("/")
        if path in ("/v1/models", "/models"):
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": _provider["model_id"],
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": _provider["owner"],
                        }
                    ],
                },
            )
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        messages = body.get("messages", [])
        response_format = body.get("response_format")
        tools = body.get("tools")
        model = body.get("model", _provider["model_id"])

        prompt, system_prompt = build_prompt(messages, response_format, tools)

        cli_name = _provider["cmd"][0]
        tools_label = f", {len(tools)} tools" if tools else ""
        print(f"  → {cli_name} ({len(prompt)} chars{tools_label}) ...",
              end="", flush=True)

        try:
            start = time.time()
            response_text, error = run_cli(prompt, system_prompt)
            elapsed = time.time() - start

            if error:
                print(f" ERROR: {error}")
                self._send_json(
                    500,
                    {"error": {"message": error, "type": "cli_error"}},
                )
                return

            # Parse tool calls from response if tools were provided
            tool_calls = None
            content = response_text
            if tools and response_text:
                tool_calls, content = parse_tool_calls(response_text)
                if tool_calls:
                    names = [tc["function"]["name"] for tc in tool_calls]
                    print(f" OK ({elapsed:.1f}s, tool_calls: {names})")
                else:
                    print(f" OK ({elapsed:.1f}s, {len(response_text)} chars, no tool call)")
            else:
                print(f" OK ({elapsed:.1f}s, {len(response_text)} chars)")

            self._send_json(
                200,
                make_completion_response(content, model, tool_calls),
            )

        except subprocess.TimeoutExpired:
            print(" TIMEOUT")
            self._send_json(
                504,
                {"error": {"message": f"{cli_name} timed out (600s)", "type": "timeout"}},
            )
        except Exception as e:
            print(f" EXCEPTION: {e}")
            self._send_json(
                500,
                {"error": {"message": str(e), "type": "internal_error"}},
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CLI LLM Proxy — OpenAI-compatible API powered by Claude Code / Codex"
    )
    parser.add_argument(
        "--provider", choices=["claude", "codex"], default="claude",
        help="Which CLI to use as backend (default: claude)"
    )
    parser.add_argument("--port", type=int, default=8888, help="Port (default: 8888)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    args = parser.parse_args()

    global _provider
    _provider = PROVIDERS[args.provider]

    print(f"Provider: {args.provider}")
    if not check_provider(_provider):
        sys.exit(1)

    server = ThreadingHTTPServer((args.host, args.port), ProxyHandler)

    model_id = _provider["model_id"]
    print()
    print(f"Proxy running at http://{args.host}:{args.port}/v1")
    print(f"  Features: tool-calling emulation, rate-limit auto-wait")
    print()
    print("Add to your .env:")
    print(f"  LLM_API_KEY=dummy")
    print(f"  LLM_BASE_URL=http://{args.host}:{args.port}/v1")
    print(f"  LLM_MODEL_NAME={model_id}")
    print()
    print("Waiting for requests... (Ctrl+C to stop)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
