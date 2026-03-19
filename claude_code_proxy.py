#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI LLM Proxy — OpenAI-compatible API server powered by Claude Code or Codex CLI.
Use your CLI subscription as an LLM backend for MiroFish.

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
import subprocess
import sys
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_prompt(messages, response_format=None):
    """Convert OpenAI-format messages into a prompt string + optional system prompt."""
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

    if response_format and response_format.get("type") == "json_object":
        prompt += (
            "\n\nYou must respond with valid JSON only. "
            "No markdown code fences, no explanation, just the JSON object."
        )

    return prompt, system_prompt


def make_completion_response(content, model):
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def run_cli(prompt, system_prompt=None):
    """Run the active provider CLI and return (response_text, error)."""
    import tempfile, os

    p = _provider
    cmd = list(p["cmd"])

    # Build the full input text
    full_input = prompt
    if system_prompt:
        if p["system_flag"]:
            # Provider supports a dedicated system prompt flag (e.g. claude)
            cmd.extend([p["system_flag"], system_prompt])
        else:
            # Prepend system prompt into the user prompt (e.g. codex)
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
        timeout=300,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"exited with code {result.returncode}"
        if out_file and os.path.exists(out_file):
            os.unlink(out_file)
        return None, error_msg

    # Read response: from -o file if codex, otherwise from stdout
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

    return response, None


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

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
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
        model = body.get("model", _provider["model_id"])

        prompt, system_prompt = build_prompt(messages, response_format)

        cli_name = _provider["cmd"][0]
        print(f"  → {cli_name} ({len(prompt)} chars) ...", end="", flush=True)

        try:
            start = time.time()
            response_text, error = run_cli(prompt, system_prompt)
            elapsed = time.time() - start

            if error:
                print(f" ERROR: {error}")
                self._send_json(500, {"error": {"message": error, "type": "cli_error"}})
                return

            print(f" OK ({elapsed:.1f}s, {len(response_text)} chars)")
            self._send_json(200, make_completion_response(response_text, model))

        except subprocess.TimeoutExpired:
            print(" TIMEOUT")
            self._send_json(504, {"error": {"message": f"{cli_name} timed out (300s)", "type": "timeout"}})
        except Exception as e:
            print(f" EXCEPTION: {e}")
            self._send_json(500, {"error": {"message": str(e), "type": "internal_error"}})


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
