# Dataclaw Agent

A local-first, extensible data science agent. Dataclaw provides an event-loop agent architecture with swappable providers, a hook-based plugin system, and a clean React frontend — all wired together with the [AG-UI protocol](https://docs.ag-ui.com) for standardized agent-to-UI communication.

Its built on the current opensource tools, Dataclaw = Openclaw+ Gbrain from Gary tan + Andrej Karpathy- Auto research + A custom harness layer that handles analytics and specific data science tasks. Its an experimental Beta release. This is mostly built with AI.

***A few things that would be great additions in near future will be - Nvidia open shell to make it more secure, A sub agent which can review the v1 analysis and provide feedback for improvement (its manaual now), would be good to add a hermes version to see if thats more stable vs open claw, a defined auto research skill - that runs expeiremnts on existing projects. - collaborations are welcome. 

> **Local use only.** Dataclaw is designed to run on your local machine or a trusted private server. It allows arbitrary code execution (shell commands, Python notebooks) on the host device. API keys and credentials are stored as plain text in `~/.dataclaw/dataclaw.config.json`. Do not expose Dataclaw to the public internet without additional security measures.

---

## Quick Start

### Option 1: Run directly with uv

```bash
uv run dataclaw
```

On first run this installs Python dependencies, builds the React frontend, and starts the server on http://localhost:8000.

**Prerequisites:**
- [Python 3.12+](https://python.org/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Node.js 22+](https://nodejs.org/) (for the frontend build)

### Option 2: Docker — Standalone (Direct LLM)

For running with a direct LLM provider (Anthropic, OpenAI, Gemini) without OpenClaw:

```bash
docker compose up --build
```

This builds and runs Dataclaw in a container with the UI pre-built. The server starts on http://localhost:8000. Configure your LLM API key on the Config page or via environment:

```bash
ANTHROPIC_API_KEY=sk-... docker compose up --build
```

| | |
|---|---|
| **Port** | `8000` — Dataclaw UI and API |
| **Volumes** | `./data` — shared data files |
| | `./workspaces` — workspace storage |

### Option 3: Docker — Bundled with OpenClaw

For the full experience with OpenClaw as the agent runtime (recommended):

```bash
docker compose -f docker-compose.bundled.yml up --build
```

This builds a single container with both Dataclaw and OpenClaw pre-installed. On first start it bootstraps the OpenClaw gateway, installs the bridge plugins, and configures default tokens. All state persists under `docker-data/`.

**First-run setup:**

1. Start the container — it will bootstrap OpenClaw automatically
2. Open http://localhost:8000/config
3. Click **Configure Model** to authenticate your model provider through the embedded terminal
4. The container will restart when OpenClaw restarts after model configuration — this is expected
5. Start using Dataclaw at http://localhost:8000

For full OpenClaw onboarding beyond the model provider, use the integrated terminal in the Dataclaw UI or `docker exec -it <container> bash`.

| | |
|---|---|
| **Ports** | `8000` — Dataclaw UI and API |
| | `18789` — OpenClaw gateway (WebSocket + Control UI) |
| | `18790` — OpenClaw bridge |
| **Volumes** | `docker-data/data` — shared data files |
| | `docker-data/workspaces` — workspace storage |
| | `docker-data/openclaw` — OpenClaw config, plugins, sessions |
| | `docker-data/dataclaw` — Dataclaw config and sessions |

All ports are overridable via environment variables (`DATACLAW_PORT`, `OPENCLAW_GATEWAY_PORT`, `OPENCLAW_BRIDGE_PORT`). The data directory can be changed with `DOCKER_DATA_DIR`.

The container runs both processes and exits if either one dies, relying on Docker's `restart: unless-stopped` policy to bring everything back up together.

**Prerequisites:**
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

---

## Setup Guide

### 1. Configure the Agent Backend

Open the Config page at http://localhost:8000/config.

**Recommended: OpenClaw** — a full-featured agent runtime with multi-model support, memory, and tool orchestration.

1. Select **OpenClaw** as the Agent Backend
2. Click **Install OpenClaw** and follow the prompts
3. Once installed, configure the OpenClaw model (e.g. Claude, GPT-4, Gemini) via the model selector

**Alternative: Direct LLM** — connect directly to an LLM API without OpenClaw.

Select `anthropic`, `openai`, or `gemini` as the backend and enter your API key. Or set via environment:

```bash
ANTHROPIC_API_KEY=sk-... uv run dataclaw
```

### 2. Install OpenClaw Plugins (if using OpenClaw)

> **Note:** If you're using the bundled Docker image (`docker-compose.bundled.yml`), this step is handled automatically on first start. Skip to step 3.

After OpenClaw is installed and running, install the Dataclaw bridge plugins from the Config page:

1. Scroll to the **OpenClaw Bridge** section
2. Click **Install** next to `dataclaw-tools` — this exposes Dataclaw's tools to the OpenClaw agent
3. Click **Install** next to `dataclaw-frontend` — this routes messages between Dataclaw and OpenClaw
4. Both plugins install automatically with the correct tokens and API URL

The plugins are located in `openclaw-plugins/` and are installed into the running OpenClaw instance.

### 3. Create a Project

Navigate to **Projects** in the sidebar and create a new project. Each project gets:
- An isolated Python environment for notebooks
- A dedicated file workspace
- MLflow experiment tracking
- Scoped chat sessions

---

## Dependencies

### System Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | Required for backend |
| Node.js | 22+ | Required for frontend build (not needed with Docker) |
| uv | latest | Python package manager ([install](https://docs.astral.sh/uv/)) |

### Python Dependencies

Core: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `langgraph`, `langchain`, `ag-ui-protocol`

LLM providers (optional, based on backend): `langchain-anthropic`, `langchain-openai`, `langchain-google-genai`

Plugins: `duckdb`, `nbformat`, `jupyter_client`, `mlflow`, `browser-use`

All dependencies are managed by `uv` and installed automatically on first run.

### Frontend Dependencies

`react`, `antd`, `vite`, `react-router-dom`, `react-markdown` — installed via `npm install` during the frontend build.

---

## Architecture

```
React UI (:8000)  ──POST /api/agent (SSE stream)──>  FastAPI (:8000)
                                                         │
                                                   Agent Pipeline
                                                   (hooks between
                                                    every stage)
                                                         │
                                          userQuery ─> compaction
                                          systemPrompt ─> memory
                                          skill ─> toolAvailability
                                          agent ─> [tool loop]
                                                         │
                                               ┌─────────┴─────────┐
                                               │                   │
                                          Direct LLM          OpenClaw
                                          (LangChain)         (External)
```

### Agent Pipeline

Every user message flows through a pipeline of **providers**, with **hooks** between each stage:

```
userQuery -> userQueryHook -> compaction -> postCompactionHook ->
systemPrompt -> postSystemPromptHook -> memory -> postMemoryHook ->
skill -> postSkillHook -> toolAvailability -> postToolAvailabilityHook ->
agent -> callAgent

If the agent makes tool calls:
  preToolCallHook -> toolExecution -> postToolCallHook -> (loop back)

If the agent returns a message:
  postAgentMessageHook -> persist to session -> stream to user
```

### Connection Resilience

The agent loop runs as a background task, decoupled from the SSE stream. Events are logged in an in-memory **Run Tracker**, allowing:
- **Reconnection** — if the browser disconnects, it reconnects and replays missed events
- **Multi-tab** — multiple browser tabs can tail the same session
- **Cancellation** — a Stop button cancels the running agent task

---

## Project Structure

```
dataclaw/
  pyproject.toml                         # Python 3.12+, uv-managed
  Dockerfile                             # Multi-stage build (UI + backend)
  docker-compose.yml                     # Single-command Docker deployment
  dataclaw/                              # Backend package
    __init__.py
    __main__.py                          # CLI: uv run dataclaw
    schema.py                            # Message class, ToolDefinition
    state.py                             # AgentState TypedDict
    config/                              # Configuration (paths, schema, resolver)
    hooks/                               # Pipeline hook system
    providers/                           # Provider protocols + implementations
    api/                                 # FastAPI (app factory, routers, run tracker)
    storage/                             # Session + skill persistence
    plugins/                             # Plugin system (discovery, registry)

  plugins/                               # Installable plugins
    dataclaw-workspace/                  #   File I/O + shell execution
    dataclaw-data/                       #   Dataset registry + DuckDB querying
    dataclaw-notebooks/                  #   Jupyter notebook management (isolated venvs)
    dataclaw-plans/                      #   Plan proposals + MLflow tracking
    dataclaw-projects/                   #   Project management
    dataclaw-browser/                    #   AI browser automation (feature-flagged)
    dataclaw-openclaw/                   #   OpenClaw agent bridge

  openclaw-plugins/                      # TypeScript plugins for OpenClaw runtime
    dataclaw-frontend/                   #   Channel plugin (messages Dataclaw <-> OpenClaw)
    dataclaw-tools/                      #   Tool bridge (exposes Dataclaw tools to OpenClaw)

  ui/                                    # React frontend (Vite, Ant Design, React Router)
```

---

## Plugins

Plugins are installed via pip and auto-discovered at startup:

| Plugin | Tools | Routes | Key Dependencies |
|---|---|---|---|
| `dataclaw-workspace` | 6 (file I/O, shell exec) | — | stdlib |
| `dataclaw-data` | 6 (list, profile, preview, query, describe, docs) | `/api/data/*` | duckdb |
| `dataclaw-notebooks` | 13 (open, close, read, edit, execute, etc.) | `/api/notebooks` | nbformat, jupyter_client |
| `dataclaw-plans` | 5 (propose, update, list, get, mlflow) | `/api/plans/*`, `/api/mlflow/*` | mlflow |
| `dataclaw-projects` | — | `/api/projects/*` | — |
| `dataclaw-browser` | 1 (browser_use) | — | browser-use |
| `dataclaw-openclaw` | — (replaces agent provider) | `/api/tools/{name}/call` | httpx |

### Notebook Isolation

Each project gets its own isolated Python venv (created via `uv`). When creating a project, you can choose:
- **New isolated environment** (default) — auto-created venv with configurable packages
- **System Python** — no isolation
- **Custom Python binary** — point at any interpreter

The `dataclaw_data` runtime package is auto-injected into every kernel so notebooks can access datasets:
```python
import dataclaw_data
df = dataclaw_data.get_dataframe("dataset_id", table_name="query_name")
```

---

## Configuration

All runtime data under `~/.dataclaw/` (override with `$DATACLAW_HOME`):

```
~/.dataclaw/
  dataclaw.config.json     # Main config (credentials stored as plain text)
  sessions/                # Chat session JSON files
  skills/                  # Skill markdown files
  workspaces/              # Per-workspace file storage + notebooks
  plugins/                 # Plugin data (datasets, plans, venvs, etc.)
```

### Environment Variables

| Variable | Config path | Default |
|---|---|---|
| `DATACLAW_LLM_BACKEND` | `llm.backend` | `openclaw` |
| `ANTHROPIC_API_KEY` | `llm.anthropic.api_key` | |
| `OPENAI_API_KEY` | `llm.openai.api_key` | |
| `GOOGLE_API_KEY` | `llm.gemini.api_key` | |
| `DATACLAW_MAX_TURNS` | `app.max_turns` | `30` |
| `DATACLAW_PORT` | `app.port` | `8000` |

Config changes to the agent backend are **hot-reloaded** — no server restart needed.

---

## Security Considerations

Dataclaw is intended for **local/private use only**:

- **Code execution**: The workspace plugin runs arbitrary shell commands. The notebook plugin executes arbitrary Python. Both run with the permissions of the host process.
- **Credential storage**: API keys, tokens, and connection strings are stored as plain text in `~/.dataclaw/dataclaw.config.json`.
- **No authentication**: The API has no authentication layer. Anyone who can reach port 8000 can access all data and execute commands.
- **Dataset queries**: SQL queries are restricted to read-only (SELECT/WITH/SHOW), but the shell execution tool has no such restriction.

Do not expose Dataclaw to untrusted networks without adding authentication, TLS, and sandboxing.

---

## Development

### Run tests

```bash
uv sync --extra dev
uv run pytest tests/ -v                          # core tests
uv run pytest plugins/dataclaw-data/tests/ -v    # data plugin
uv run pytest plugins/dataclaw-notebooks/tests/  # notebooks
```

### Rebuild the frontend

The frontend is built automatically on first run. To force a rebuild:

```bash
rm -rf ui/dist && uv run dataclaw
```

### Sync OpenClaw tool manifest

After adding/removing tools, regenerate the static manifest:

```bash
cd openclaw-plugins/dataclaw-tools
./sync-manifest.sh    # fetches from GET /api/tools (server must be running)
```

---

## Tech Stack

**Backend:** Python 3.12+, FastAPI, LangGraph, LangChain, DuckDB, MLflow, uv

**Frontend:** React 19, TypeScript, Vite, Ant Design

**Protocol:** [AG-UI](https://docs.ag-ui.com) (Server-Sent Events)

**Agent Backends:** OpenClaw (recommended), Anthropic Claude, OpenAI, Google Gemini, Mock

---

## License

MIT
