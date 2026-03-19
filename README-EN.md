<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="CodeFish Logo" width="75%"/>

Swarm Intelligence Simulation Engine powered by Claude Code / Codex
</br>
<em>Claude Code / Codex で動く群体知能シミュレーションエンジン</em>

[![GitHub Stars](https://img.shields.io/github/stars/Andyyyy64/CodeFish?style=flat-square&color=DAA520)](https://github.com/Andyyyy64/CodeFish/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/Andyyyy64/CodeFish?style=flat-square)](https://github.com/Andyyyy64/CodeFish/network)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)

[English](./README-EN.md) | [日本語](./README.md)

</div>

## Overview

**CodeFish** is a fork of [MiroFish](https://github.com/666ghj/MiroFish) that runs multi-agent simulations using only your **Claude Code** or **Codex** CLI subscription — no pay-per-token API keys required.

Upload a text file (news articles, reports, novels, etc.) as a seed, write a prompt in natural language, and CodeFish automatically builds a parallel world populated by thousands of agents with independent personalities, memories, and behavioral logic. Through swarm interaction, it predicts future outcomes.

> **Requirements:** Claude Code or Codex subscription + Zep Cloud (free tier is enough)
> **Additional API costs:** None (the CLI proxy leverages your existing subscription)

## Features

- **Flat-rate** — Runs entirely on your Claude Code / Codex subscription. No per-token API costs
- **Provider switching** — `--provider claude` or `--provider codex` to switch instantly
- **Japanese UI** — Full frontend localized to Japanese
- **OpenAI-compatible proxy** — `claude_code_proxy.py` wraps CLIs as an OpenAI-format API

## Workflow

1. **Graph Building** — Auto-construct a knowledge graph (GraphRAG) from seed text
2. **Environment Setup** — Entity extraction, persona generation, simulation parameter configuration
3. **Simulation** — Run multi-agent parallel simulation
4. **Report Generation** — ReportAgent analyzes simulation results and produces reports
5. **Deep Interaction** — Chat with any agent in the simulated world

## Quick Start

### Prerequisites

| Tool | Version | Description | Check |
|------|---------|-------------|-------|
| **Node.js** | 18+ | Frontend runtime | `node -v` |
| **Python** | ≥3.11, ≤3.12 | Backend runtime | `python --version` |
| **uv** | Latest | Python package manager | `uv --version` |
| **Claude Code** or **Codex** | Latest | LLM backend | `claude --version` / `codex --version` |

### 1. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# LLM API — via CLI proxy
LLM_API_KEY=dummy
LLM_BASE_URL=http://127.0.0.1:8888/v1
LLM_MODEL_NAME=claude-code   # or codex

# Zep Cloud (free tier is sufficient)
# Get your API key at https://app.getzep.com/
ZEP_API_KEY=your_zep_api_key
```

### 2. Install Dependencies

```bash
# Install all dependencies at once
npm run setup:all
```

Or step by step:

```bash
npm run setup          # Node dependencies (root + frontend)
npm run setup:backend  # Python dependencies (backend, auto-creates venv)
```

### 3. Start the CLI Proxy

```bash
# Using Claude Code
python3 claude_code_proxy.py --provider claude --port 8888

# Using Codex
python3 claude_code_proxy.py --provider codex --port 8888
```

### 4. Start Services

```bash
# Start frontend + backend together
npm run dev
```

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:5001`
- CLI Proxy: `http://127.0.0.1:8888/v1`

### Docker Deployment

```bash
cp .env.example .env
# Edit .env, then:
docker compose up -d
```

## Usage Examples

| Seed File | Prompt |
|-----------|--------|
| news_article.txt | "If this company holds a public apology, how will social media react?" |
| product_launch.txt | "How will the developer community respond to this product release?" |
| oss_trends.txt | "What kind of OSS project would get the most GitHub stars?" |
| novel_first_half.txt | "Predict the ending of this story and character actions" |
| policy_draft.pdf | "How will citizens react if this policy is enacted?" |

## Acknowledgments

- Forked from: [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj
- Simulation engine: [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI

## License

[AGPL-3.0](./LICENSE)
