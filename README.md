# Dataclaw Agent

A local-first, extensible data science agent. Dataclaw provides an event-loop agent architecture with swappable providers, a hook-based plugin system, and a clean React frontend — all wired together with the [AG-UI protocol](https://docs.ag-ui.com) for standardized agent-to-UI communication.

Its built on the current opensource tools, Dataclaw = Openclaw+ Gbrain from Gary tan + Andrej Karpathy- Auto research + A custom harness layer that handles analytics and specific data science tasks. Its an experimental Beta release. This is mostly built with AI.

***A few things that would be great additions in near future will be - Nvidia open shell to make it more secure, A sub agent which can review the v1 analysis and provide feedback for improvement (its manaual now), would be good to add a hermes version to see if thats more stable vs open claw, a defined auto research skill - that runs expeiremnts on existing projects. - collaborations are welcome.

> **Local use only.** Dataclaw is designed to run on your local machine or a trusted private server. It allows arbitrary code execution (shell commands, Python notebooks) on the host device. API keys and credentials are stored as plain text in `~/.dataclaw/dataclaw.config.json`. Do not expose Dataclaw to the public internet without additional security measures.


https://github.com/user-attachments/assets/25dc8181-bd14-41ad-a81c-5f9fe108e30a

---

## Release 3 updates

Release 3 turns Dataclaw's analysis into a **governed, evidence-first workflow** instead of a chat that emits charts. The baseline platform could explore data and produce a report, but nothing tied a claim in that report back to the analysis that produced it, and nothing stopped an unreviewed or unsupported finding from shipping. Release 3 closes that gap end to end: exploration is recorded as durable evidence, that evidence is reviewed against explicit gates before it can be called "ready," and only approved output is versioned into a shareable artifact.

Concretely, the release introduces four ideas that build on one another:

- **A durable EDA ledger.** Exploration no longer lives only in notebook scrollback. Hypotheses and findings are proposed, updated, and recorded as first-class entries (`dataclaw-eda`), each anchored to the notebook cells or structured evidence that support it. `summarize_eda_readiness` reports whether the ledger is coherent enough to move forward.
- **A deterministic review gate.** Before a high-risk or EDA-like step is marked `ready_for_validation`, it can be routed through `dataclaw-analysis-review`, which audits coherence between claims, ledger state, and evidence anchors. Reviews raise checklist findings that must be resolved — or explicitly `accepted_with_rationale` when the user knowingly accepts the risk — and the gate stays `unknown` when a scope requires a sub-agent reviewer that has not run.
- **Versioned artifacts.** Approved HTML deliverables (reports, dashboards, model cards, living-report notes) are published as session-scoped, versioned artifacts (`dataclaw-artifacts`) that can be re-read, exported, and shared without losing their history.
- **A storyboard-first report path.** Final reports are composed deliberately — `report_design_report` builds a storyboard, `report_review_visuals` captures and records a named review decision, and `report_publish` writes a publish receipt — rather than appending chart dumps to a page.

On the UI side, Chat keeps independent and project sessions separate. In an opened session, the Reports rail distinguishes published artifacts from scratch drafts, keeps their counts beside the title, provides compact report/version controls, and previews the selected report in place. It does not change the Independent chats directory.

### Plugins and tools added or expanded in Release 3

| Area | Release 3 delta from `main` |
|---|---|
| `dataclaw-eda` (new) | An evidence-backed EDA ledger: `propose_eda_hypotheses`, `update_eda_hypothesis`, `record_eda_finding`, finding/hypothesis reads, and `summarize_eda_readiness`. |
| `dataclaw-analysis-review` (new) | Deterministic review lifecycle for plan steps, artifacts, living reports, and sessions: request a review, list and resolve findings, inspect the review gate, and list review runs. |
| `dataclaw-artifacts` (new) | Session-scoped, versioned HTML artifacts through `publish_artifact`, `read_artifact`, `list_artifacts`, `export_artifact`, `delete_artifact`, and `report_note`. |
| `dataclaw-workspace` (expanded) | Storyboard-backed report tools: `build_report`, `report_design_report`, `report_review_visuals`, `report_publish`, and `report_add_section`, alongside the existing workspace tools. |
| `dataclaw-plans` (expanded) | Stable plan-step identifiers, validation gates, and `accept_gate_risk` with an explicit audited rationale. |
| OpenClaw bridge (expanded) | Installs a snapshot of the live Dataclaw tool manifest and exposes the governed report/EDA tools to OpenClaw; reinstall it after manifest drift. |

### Bundled skills added or updated in Release 3

- Added: `structured_eda`, `insight_validation`, `analysis_review`, `artifacts`, `report_design`, `visualization`, and `dashboarding`.
- Updated: `dataclaw_data_science` routes governed EDA, review, report, and artifact work; `data_profiling` remains the compact profile path and points goal-directed exploration to `structured_eda`.
- These skills are installed from `skill-library/` and can be synchronized to the Dataclaw OpenClaw extension separately from the tool manifest.
- The **Skills page** was reworked into a two-column master–detail layout: the left column lists skills — grouped into **My Skills** (with `Custom` / `From Library` badges) and the not-yet-installed **Skill Library**, each library row carrying an inline **Install** button — while the right column renders the selected skill's full write-up. New skills can be authored inline or imported from a `.md` file.

The report workflow is HTML-first. `report_design_report` creates a storyboard-backed report, `report_review_visuals` records browser captures and a named review decision when required, `report_publish` creates the publish receipt, and `publish_artifact` versions the approved HTML for session use and export.

**How the pieces fit together (typical flow):**

1. **Explore** — `structured_eda` runs goal-directed analysis and records hypotheses and findings into the `dataclaw-eda` ledger, each anchored to notebook evidence.
2. **Validate** — `insight_validation` recomputes and pressure-tests a claim before it is recorded as a confirmed finding.
3. **Review** — `request_analysis_review` opens a deterministic gate over the plan step or session; checklist findings are resolved (or accepted with a recorded rationale) until the gate clears.
4. **Design** — `report_design` composes a storyboard-backed report from the confirmed findings, aggregate assets, and methodology.
5. **Publish** — `report_publish` records the publish receipt and `publish_artifact` versions the approved HTML into a session-scoped artifact that can be previewed in the Reports rail, exported, or synced to OpenClaw.

Each stage leaves an auditable trail, so a published report can be traced back through its review gate to the specific findings and notebook cells that support it.

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

For running with a direct LLM provider (Anthropic, OpenAI, Gemini, Codex) without OpenClaw:

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
| **Volumes** | `${DOCKER_DATA_DIR:-./docker-data}/dataclaw` — Dataclaw config, sessions, workspaces |

### Option 3: Docker — Bundled with OpenClaw

For the full experience with OpenClaw as the agent runtime:

```bash
docker compose -f docker-compose.bundled.yml up --build
```

This builds a single container with both Dataclaw and OpenClaw pre-installed. On first start it bootstraps the OpenClaw gateway, installs the `dataclaw` plugin, and configures default tokens. All state persists under `docker-data/`.

**First-run setup:**

1. Start the container — it will bootstrap OpenClaw automatically
2. Open http://localhost:8000/config
3. Click **Configure Model** to authenticate your model provider through the embedded terminal — when you close the modal a popup will remind you to restart OpenClaw so the new model takes effect (`openclaw gateway restart`, or restart the container)
4. Start using Dataclaw at http://localhost:8000

For full OpenClaw onboarding beyond the model provider, use the integrated terminal in the Dataclaw UI or `docker exec -it <container> bash`.

| | |
|---|---|
| **Ports** | `8000` — Dataclaw UI and API |
| | `18789` — OpenClaw gateway (WebSocket + Control UI) |
| | `18790` — OpenClaw bridge |
| **Volumes** | `${DOCKER_DATA_DIR:-./docker-data}/openclaw` — OpenClaw config, plugins, sessions |
| | `${DOCKER_DATA_DIR:-./docker-data}/dataclaw` — Dataclaw config, sessions, workspaces |

All ports are overridable via environment variables (`DATACLAW_PORT`, `OPENCLAW_GATEWAY_PORT`, `OPENCLAW_BRIDGE_PORT`). The data directory can be changed with `DOCKER_DATA_DIR`.

The container runs both processes and exits if either one dies, relying on Docker's `restart: unless-stopped` policy to bring everything back up together.

**Prerequisites:**
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

---

## Setup Guide

### 1. Configure the Agent Backend

Open the Config page at http://localhost:8000/config.

**OpenClaw** — a full-featured agent runtime with multi-model support, memory, and tool orchestration.

1. Select **OpenClaw** as the Agent Backend
2. Click **Install OpenClaw** and follow the prompts
3. Once installed, configure the OpenClaw model (e.g. Claude, GPT-4, Gemini) via the model selector

**Direct LLM** — connect directly to an LLM API without OpenClaw.

Select `anthropic`, `openai`, `gemini`, or `codex` as the backend and enter your API key (or sign in interactively for Codex — see [Codex authentication](#codex-authentication) below). Or set via environment:

```bash
ANTHROPIC_API_KEY=sk-... uv run dataclaw
```

#### Codex authentication

Choosing the Codex backend lets you call OpenAI's Codex models with either an API key or a ChatGPT OAuth login. The Config page shows two buttons:

- **Login with Browser** — opens an OAuth tab. After you sign in, OpenAI redirects to a `localhost:1455` callback that Codex listens on. Click the button, complete the sign-in, and the agent provider auto-reloads.
- **Device Code** — for headless or remote setups. Shows a verification URL + 8-character code; enter the code on the URL.

> **Docker fallback.** When Dataclaw runs in a container, the browser's `localhost:1455` is the host's loopback, but Codex's listener is inside the container — so the redirect 404's and the flow stalls. The Login modal exposes a *"Browser didn't redirect back automatically?"* paste field: copy the failed `http://localhost:1455/...` URL out of your browser's address bar, paste it back, and Dataclaw replays the GET inside the container so Codex's listener actually receives the auth code.

### 2. Install the OpenClaw Plugin (if using OpenClaw)

> **Note:** If you're using the bundled Docker image (`docker-compose.bundled.yml`), this step is handled automatically on first start. Skip to step 3.

After OpenClaw is installed and running, install the consolidated Dataclaw plugin from the Config page:

1. Scroll to the **OpenClaw Bridge** section
2. Click **Install** next to `dataclaw` — one plugin that exposes Dataclaw's tools to the OpenClaw agent, routes UI messages between Dataclaw and OpenClaw, and registers the Dataclaw channel.

The plugin is located at `openclaw-plugins/dataclaw/` and installs in a single click with the correct tokens, API URL, and tool allowlist entry. Each install also snapshots the current tool list and surfaces a drift banner on the Config and Tools pages when you add or remove tools, so you know when to re-install.

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
    dataclaw-workspace/                  #   File I/O + shell execution + storyboard reports
    dataclaw-data/                       #   Dataset registry + DuckDB querying
    dataclaw-notebooks/                  #   Jupyter notebook management (isolated venvs)
    dataclaw-eda/                        #   Evidence-backed EDA hypothesis/finding ledger
    dataclaw-analysis-review/            #   Deterministic analysis review + review gate
    dataclaw-artifacts/                  #   Session-scoped, versioned HTML artifacts
    dataclaw-plans/                      #   Plan proposals + MLflow tracking + validation gates
    dataclaw-projects/                   #   Project management
    dataclaw-browser/                    #   AI browser automation (feature-flagged)
    dataclaw-openclaw/                   #   OpenClaw agent bridge
    dataclaw-custom-tools/               #   User-defined Python tools + MCP server connections
    dataclaw-kaggle/                     #   Kaggle competitions, datasets, submissions
    dataclaw-gbrain/                     #   gBrain memory provider
    dataclaw-codex/                      #   OpenAI Codex sub-agent provider

  openclaw-plugins/                      # TypeScript plugins for OpenClaw runtime
    dataclaw/                            #   Consolidated plugin: tools bridge + frontend channel

  ui/                                    # React frontend (Vite, Ant Design, React Router)
```

---

## Plugins

Plugins are installed via pip and auto-discovered at startup:

| Plugin | Tools | Routes | Key Dependencies |
|---|---|---|---|
| `dataclaw-workspace` | 11 (file I/O, shell exec, report build/design/review/publish/add-section) | — | stdlib |
| `dataclaw-data` | 6 (list, profile, preview, query, describe, docs) | `/api/data/*` | duckdb |
| `dataclaw-notebooks` | 14 (open, close, read, edit, execute, display_metric, etc.) | `/api/notebooks` | nbformat, jupyter_client |
| `dataclaw-eda` | 8 (propose/update/list hypotheses, record/read/list/supersede findings, summarize readiness) | `/api/eda/*` | stdlib |
| `dataclaw-analysis-review` | 5 (request review, list/resolve findings, review gate, list runs) | `/api/analysis-review/*` | stdlib |
| `dataclaw-artifacts` | 6 (publish, read, list, export, delete, report_note) | `/api/artifacts/*` | stdlib |
| `dataclaw-plans` | 6 (propose, update, list, get, mlflow, accept_gate_risk) | `/api/plans/*`, `/api/mlflow/*` | mlflow |
| `dataclaw-projects` | — | `/api/projects/*` | — |
| `dataclaw-browser` | 1 (browser_use) + browser sub-agent | — | browser-use |
| `dataclaw-openclaw` | — (replaces agent provider) | `/api/openclaw/*`, `/api/tools/{name}/call` | httpx |
| `dataclaw-custom-tools` | dynamic (user-defined + MCP) | `/api/custom-tools/*`, `/api/mcp-servers/*` | mcp |
| `dataclaw-kaggle` | 8 (competitions, datasets, leaderboards, submissions) | `/api/kaggle/*` | kaggle SDK |
| `dataclaw-gbrain` | 2 (search, save) — registered via memory provider | — | gbrain CLI |
| `dataclaw-codex` | — (registers `codex` sub-agent type) | — | openai-codex-app-server-sdk |

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

### Auto Mode

A toggle in the chat header that lets the agent run autonomously without waiting for the user to type "go" between turns. After every assistant turn, if the agent didn't ask a question and the auto-turn budget isn't exhausted, the loop fires another turn automatically with a synthetic "continue" prompt.

- Per-session toggle — `autoMode` is stored on the chat session and survives reloads.
- Hard cap on consecutive turns — `app.max_auto_turns` (default `10`) so a runaway loop doesn't burn through credits.
- Plans proposed during auto mode are auto-approved, so a multi-step plan can execute end-to-end without UI clicks.

### Subagents

Plugins can register **sub-agent providers** (`ctx.sub_agent_registry.register(...)`) that the parent agent can delegate work to via `delegate_to_subagent`. Each provider declares an `agent_type` and exposes its own config schema. Currently shipped:

| `agent_type` | Source | Use |
|---|---|---|
| `llm` | `DefaultSubAgentProvider` (built-in) | Spin up a fresh LangGraph loop with a focused system prompt and a scoped tool set |
| `browser` | `dataclaw-browser` | Hand off web tasks to `browser-use` (Playwright) |
| `codex` | `dataclaw-codex` | Hand off coding work to OpenAI Codex via the `codex` CLI/app-server |

Subagent definitions are managed in the **Subagents** page (`/subagents`) and can be scoped per-project. The parent agent's `list_subagents` tool returns only the subagents the current session has been allowed to use.

### Custom Tools & MCP Servers

The `dataclaw-custom-tools` plugin lets you extend the tool surface without touching the codebase:

- **Custom Python tools** — drop a `.py` file under `~/.dataclaw/tools/` exporting a `tool_definition` dict + a callable. They're loaded at startup and on hot-reload (`POST /api/custom-tools/reload`).
- **MCP servers** — register an [MCP](https://modelcontextprotocol.io/) server (stdio or HTTP) from the **Tools** page; its tools are auto-discovered and exposed under the same registry the agent loop uses.

Adding or removing tools triggers a drift banner on the OpenClaw bridge install card so you know to re-install the bridge plugin (or click the bundled image's auto-install) to refresh the manifest in OpenClaw.

### Kaggle Integration

The `dataclaw-kaggle` plugin wires up the Kaggle API end-to-end. Configure your Kaggle username + API key on the Config page (`plugins.kaggle.kaggle_username` / `plugins.kaggle.kaggle_key`), then the agent gets:

- `list_competitions`, `competition_details`, `leaderboard`, `download_competition`
- `search_datasets`, `download_dataset`
- `submit`, `submissions`

Downloaded competition/dataset archives can be auto-registered as Dataclaw datasets when `auto_register_datasets` is on (default), so the agent can immediately profile and query them.

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
| `OPENAI_API_KEY` | `llm.openai.api_key` / `llm.codex.api_key` | |
| `GOOGLE_API_KEY` | `llm.gemini.api_key` | |
| `CODEX_MODEL` | `llm.codex.model` | `gpt-5.5` |
| `CODEX_AUTH_MODE` | `llm.codex.auth_mode` | `default` (OAuth) — `api_key` for direct |
| `DATACLAW_MAX_TURNS` | `app.max_turns` | `30` |
| `DATACLAW_PORT` | `app.port` | `8000` |
| `DATACLAW_TOKEN` | `plugins.openclaw.token` | `dataclaw-local` |
| `DATACLAW_OPENCLAW_URL` | `plugins.openclaw.url` | `http://127.0.0.1:18789` |

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

The bridge plugin's tool manifest (`openclaw.plugin.json contracts.tools` + `src/tools/tool-manifest.generated.ts`) is regenerated automatically every time you click **Install** on the OpenClaw Bridge — the install service snapshots the live tool registry at install time. Add a new tool, watch the drift banner appear on the Config / Tools pages, click Install, done.

If you'd rather invoke the install flow programmatically:

```bash
curl -X POST http://localhost:8000/api/openclaw/plugins/dataclaw/install
```

---

## Tech Stack

**Backend:** Python 3.12+, FastAPI, LangGraph, LangChain, DuckDB, MLflow, uv

**Frontend:** React 19, TypeScript, Vite, Ant Design

**Protocol:** [AG-UI](https://docs.ag-ui.com) (Server-Sent Events)

**Agent Backends:** OpenClaw (recommended), Anthropic Claude, OpenAI, OpenAI Codex (OAuth or API key), Google Gemini, Mock

**Sub-agents:** built-in LLM, browser-use, Codex

---

## License

MIT
