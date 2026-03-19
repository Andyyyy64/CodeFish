<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="CodeFish Logo" width="75%"/>

Claude Code / Codex で動く群体知能シミュレーションエンジン
</br>
<em>Swarm Intelligence Simulation Engine powered by Claude Code / Codex</em>

[![GitHub Stars](https://img.shields.io/github/stars/Andyyyy64/CodeFish?style=flat-square&color=DAA520)](https://github.com/Andyyyy64/CodeFish/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/Andyyyy64/CodeFish?style=flat-square)](https://github.com/Andyyyy64/CodeFish/network)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)

[English](./README-EN.md) | [日本語](./README.md)

</div>

## 概要

**CodeFish** は [MiroFish](https://github.com/666ghj/MiroFish) をフォークし、**Claude Code** および **Codex** のCLIサブスクリプションだけでマルチエージェントシミュレーションを実行できるようにしたエンジンです。

テキストファイル（ニュース記事、レポート、小説など）をシードとしてアップロードし、自然言語でプロンプトを書くだけで、数千体のエージェントが独立した人格・記憶・行動ロジックを持つパラレルワールドを自動構築。群体インタラクションを通じて未来の動向を予測します。

> **必要なもの:** Claude Code または Codex のサブスクリプション + Zep Cloud（無料枠で十分）
> **追加のAPI費用:** なし（CLIプロキシ経由で既存サブスクを活用）

## 特徴

- **定額制** — Claude Code / Codex のサブスクだけで動く。従量課金のAPI不要
- **プロバイダー切替** — `--provider claude` or `--provider codex` で即座に切り替え
- **日本語UI** — フロントエンド全画面を日本語化済み
- **OpenAI互換プロキシ** — `claude_code_proxy.py` がCLIをOpenAI API形式でラップ

## ワークフロー

1. **グラフ構築** — シードテキストから知識グラフ（GraphRAG）を自動構築
2. **環境構築** — エンティティ抽出、ペルソナ生成、シミュレーションパラメータ設定
3. **シミュレーション** — マルチエージェント並列シミュレーション実行
4. **レポート生成** — ReportAgentがシミュレーション結果を分析・レポート化
5. **深層インタラクション** — シミュレーション世界の任意のAgentと対話可能

## クイックスタート

### 前提条件

| ツール | バージョン | 説明 | 確認コマンド |
|--------|-----------|------|-------------|
| **Node.js** | 18+ | フロントエンド実行環境 | `node -v` |
| **Python** | ≥3.11, ≤3.12 | バックエンド実行環境 | `python --version` |
| **uv** | 最新版 | Pythonパッケージマネージャ | `uv --version` |
| **Claude Code** or **Codex** | 最新版 | LLMバックエンド | `claude --version` / `codex --version` |

### 1. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集：

```env
# LLM API — CLIプロキシ経由
LLM_API_KEY=dummy
LLM_BASE_URL=http://127.0.0.1:8888/v1
LLM_MODEL_NAME=claude-code   # or codex

# Zep Cloud（無料枠で十分）
# https://app.getzep.com/ でAPIキーを取得
ZEP_API_KEY=your_zep_api_key
```

### 2. 依存関係のインストール

```bash
# 全依存一括インストール
npm run setup:all
```

または個別に：

```bash
npm run setup          # Node依存（ルート + フロントエンド）
npm run setup:backend  # Python依存（バックエンド、仮想環境自動作成）
```

### 3. CLIプロキシの起動

```bash
# Claude Code を使う場合
python3 claude_code_proxy.py --provider claude --port 8888

# Codex を使う場合
python3 claude_code_proxy.py --provider codex --port 8888
```

### 4. サービスの起動

```bash
# フロントエンド + バックエンドを同時起動
npm run dev
```

- フロントエンド: `http://localhost:3000`
- バックエンド API: `http://localhost:5001`
- CLIプロキシ: `http://127.0.0.1:8888/v1`

### Docker デプロイ

```bash
cp .env.example .env
# .env を編集後:
docker compose up -d
```

## 使い方の例

| シードファイル | プロンプト |
|--------------|-----------|
| ニュース記事.txt | 「この企業が謝罪会見を開いた場合、SNS上の世論はどう推移するか」 |
| 製品リリース情報.txt | 「この製品が発売されたら、開発者コミュニティの反応は？」 |
| OSSトレンドまとめ.txt | 「最もGitHubスターを集めるOSSプロジェクトはどんなもの？」 |
| 小説の前半.txt | 「この物語の結末はどうなるか。登場人物の行動を予測して」 |
| 政策草案.pdf | 「この政策が施行されたら市民の反応は？」 |

## 謝辞

- フォーク元: [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj
- シミュレーションエンジン: [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI

## ライセンス

[AGPL-3.0](./LICENSE)
