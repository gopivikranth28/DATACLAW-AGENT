# Dataclaw Agent

A local-first, extensible data science agent. Dataclaw provides an event-loop agent architecture with swappable providers, a hook-based plugin system, and a React frontend — all wired together with the [AG-UI protocol](https://docs.ag-ui.com) for standardized agent-to-UI communication.

It combines OpenClaw, gBrain-style memory, notebook execution, and a custom analytics harness. It is an experimental beta and is built primarily with AI assistance. Release 3 adds a governed structured-EDA workflow, analytical review gates, versioned artifacts, a storyboard-based report builder with evidence-bound visual authoring and publish-time integrity gates, and a session-centric chat console.

> **Local use only.** Dataclaw is designed to run on your local machine or a trusted private server. It allows arbitrary code execution (shell commands, Python notebooks) on the host device. API keys and credentials are stored as plain text in `~/.dataclaw/dataclaw.config.json`. Do not expose Dataclaw to the public internet without additional security measures.


https://github.com/user-attachments/assets/25dc8181-bd14-41ad-a81c-5f9fe108e30a

---

## Release 3: Governed Analytics and Publishing

The `release3` branch turns a local analysis session into a traceable workflow: frame the question, test hypotheses in notebooks, record validated findings, review high-risk work, and publish a self-contained interactive report or artifact.

| Area | What Release 3 adds | What you can do |
|---|---|---|
| Structured EDA | A persistent hypothesis and finding ledger with evidence, confidence, caveats, validation state, and readiness checks | Run goal-directed exploration; preserve rejected or superseded findings; decide whether a dataset is ready for querying, a dashboard, or modelling |
| Plans and gates | Stable plan-step IDs, required validation gates, explicit risk acceptance, and MLflow run access | Propose a multi-step analysis, track outputs, and keep a completed step from being marked ready before required checks pass |
| Analysis review | Deterministic review checks plus an optional read-only LLM reviewer | Audit claims, denominator/grain, reproducibility, visual honesty, data-quality caveats, and hypothesis hygiene before presenting results |
| Report builder | Typed sections, editorial storyboard review, runtime visual-authoring plans, a v7 quality rubric, regeneration recipes, and explicit draft → designed → published states | Build narrative reports with metrics, evidence-backed charts, interactive tables, filters, methodology, evidence traces, and source-bound publish receipts |
| Artifacts | Versioned, session-scoped HTML artifacts and a living-report event log | Publish, revise, preview, export, and inspect reports, dashboards, and other analytical HTML safely |
| Chat console | Separate independent and project chats, a compact timestamped work log, execution-aware composer, and a session rail for plans, files, reports, datasets, experiments, and scope | Follow what the agent did, review durable published reports separately from scratch drafts, inspect session/project files, and keep project work in its project |
| OpenClaw bridge | Live tool-manifest snapshots, drift detection, install/reinstall, and skill sync | Keep OpenClaw's Dataclaw extension aligned with the tools and skills available in the local UI |

### A typical Release 3 workflow

1. Create a project and register or load data.
2. Propose an analysis plan, then use the structured-EDA tools to maintain hypotheses and findings as notebook evidence is produced.
3. Run an analysis review for a completed high-risk step, artifact, dashboard, or report; resolve findings or explicitly accept a gated risk with rationale.
4. In Chat, ask for a complete report or ask the agent to continue a draft. The agent selects the appropriate report workflow, plans only from typed source facts, and surfaces whether the result is a draft, designed report, or published report.
5. For a release requiring visual approval, inspect the generated desktop/webview browser evidence and record an approved visual review. The gate also checks deterministic rendered-page semantics such as hierarchy, evidence context, and editorial findings.
6. Ask the agent to version or share the result from the session. It publishes the artifact with its storyboard and source-bound regeneration recipe, and can produce a self-contained HTML export including the Plotly runtime needed by interactive charts.

The report workflow is HTML-first. DOCX conversion remains best-effort and should not be treated as the primary publish format. The rendered-page semantic audit is deterministic browser/DOM checking, not a learned vision judgment.

### Chat console

Chat is organized around sessions. **Independent chats** are personal sessions listed outside a project; project chats are listed only inside their project. The focused chat view keeps the transcript and composer centered, groups agent work into concise timestamped notebook-style logs, and adapts the composer while a run, queue, or plan approval is active.

The session rail provides Plans, Files, Reports, Datasets, Experiments, and Scope. Reports distinguish durable, versioned published artifacts from session-scoped scratch drafts. In an opened independent or project session, the Reports panel keeps published/scratch counts beside its title, uses compact report and version selectors, and previews the selected report in place; it does not alter the Independent chats directory. Files retain session/project workspace grouping and can be sorted by name or size. The supporting [critique and decision log](docs/ui-upgrade/chat-redesign.md), [PRD](docs/ui-upgrade/chat-redesign-prd.md), [build specification](docs/ui-upgrade/chat-redesign-spec.md), and [clickable mock](docs/ui-upgrade/mockups/chat-redesign.html) document the design and implementation rationale.

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
    dataclaw-workspace/                  #   File I/O + shell execution
    dataclaw-data/                       #   Dataset registry + DuckDB querying
    dataclaw-notebooks/                  #   Jupyter notebook management (isolated venvs)
    dataclaw-plans/                      #   Plans, gates, risk acceptance + MLflow tracking
    dataclaw-eda/                        #   Structured EDA hypothesis/finding ledger
    dataclaw-analysis-review/            #   Deterministic and sub-agent analysis reviews
    dataclaw-artifacts/                  #   Versioned HTML artifacts + living-report log
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
| `dataclaw-workspace` | 10 (file I/O, shell exec, report design/publish) | — | stdlib, Plotly runtime |
| `dataclaw-data` | 6 (list, profile, preview, query, describe, docs) | `/api/data/*` | duckdb |
| `dataclaw-notebooks` | 13 (open, close, read, edit, execute, etc.) | `/api/notebooks` | nbformat, jupyter_client |
| `dataclaw-plans` | 6 (propose, update, inspect, MLflow, gate-risk acceptance) | `/api/plans/*`, `/api/mlflow/*` | mlflow |
| `dataclaw-eda` | 8 (hypotheses, findings, readiness) | `/api/eda/*` | stdlib |
| `dataclaw-analysis-review` | 5 (run, list, resolve, gate, history) | `/api/analysis-review/*` | stdlib |
| `dataclaw-artifacts` | 6 (publish, revise, read, list, export, notes) | `/api/artifacts/*` | stdlib, Plotly runtime |
| `dataclaw-projects` | — | `/api/projects/*` | — |
| `dataclaw-browser` | 1 (browser_use) + browser sub-agent | — | browser-use |
| `dataclaw-openclaw` | — (replaces agent provider) | `/api/openclaw/*`, `/api/tools/{name}/call` | httpx |
| `dataclaw-custom-tools` | dynamic (user-defined + MCP) | `/api/custom-tools/*`, `/api/mcp-servers/*` | mcp |
| `dataclaw-kaggle` | 8 (competitions, datasets, leaderboards, submissions) | `/api/kaggle/*` | kaggle SDK |
| `dataclaw-gbrain` | 2 (search, save) — registered via memory provider | — | gbrain CLI |
| `dataclaw-codex` | — (registers `codex` sub-agent type) | — | openai-codex-app-server-sdk |

Plugin discovery is dependency-aware: the EDA ledger depends on plans, notebooks, and artifacts; analysis review depends on plans, EDA, artifacts, and projects. The **Config** and **Tools** UI surfaces the live registry, while the OpenClaw install snapshot shows whether the extension's manifest has drifted.

### Skills

Skills are Markdown instructions that guide the agent at prompt time. They are separate from executable tools: a skill explains a reliable workflow; a tool performs the action. The **Skills** page lets you create, edit, delete, browse, preview, and install skills.

Release 3 ships a bundled `skill-library/` covering:

- structured EDA, data profiling, SQL analysis, insight validation, and notebook reporting;
- visualisation, dashboarding, versioned artifacts, and report design;
- analysis review and the end-to-end Dataclaw data-science workflow.

Installing a bundled skill copies it to `~/.dataclaw/skills/` with its library source and content hash. Dataclaw detects when an installed library skill's body differs from the bundled version; refresh it by deleting and reinstalling it in the UI, or use the library install API with `?force=true` when an overwrite is intended. For safety, a publish-quality check blocks a report when an installed library skill is stale. The prompt resolver uses current bundled guidance and exposes a freshness warning rather than silently following obsolete instructions.

When the OpenClaw bridge is installed, the Skills page can also copy an installed skill into the Dataclaw OpenClaw extension or remove that synced copy. This is separate from tool-manifest sync: after adding or removing tools, reinstall/sync the bridge plugin as described below.

### Report Builder and Artifacts

Users normally request reports and publishing in Chat or through the artifact/report UI; they do not need to call tool names directly. The names below describe the capabilities available to the agent and to API integrators.

The workspace plugin provides two complementary report paths:

- `report_design_report` turns findings and aggregate analysis assets into a typed storyboard, applies a bounded critique pass, renders a report, and returns a **designed** result that still needs explicit publishing.
- `report_add_section` appends typed sections to a living **draft**. Supported sections include headers, metric rows, narrative bands, findings, methodology, evidence traces, Plotly charts, chart interpretations, filterable charts, interactive tables, chart-table explorers, selectors, and entity-card grids.
- `report_publish` runs the report-quality rubric and a browser/static runtime smoke check before returning a **published** result. It produces self-contained HTML; interactive charts embed Plotly so a downloaded report can render without a CDN.

`dataclaw-artifacts` is the durable sharing layer. `publish_artifact` stores a session-scoped artifact version, `read_artifact` retrieves clean source for revision, `export_artifact` creates a self-contained export, and `report_note` records a note in the living-report log. Artifact previews are served with a restrictive CSP and sandboxed frame.

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

Release 3 also registers an `analysis-reviewer` definition. It is an `llm` subagent with a read-only, review-specific tool allowlist. `request_analysis_review(require_subagent=true)` uses it in addition to deterministic checks; if the reviewer cannot run, the gate stays unknown instead of claiming a completed review. This reviewer is intentionally constrained to auditing evidence, hypotheses, findings, and artifact metadata — it does not execute notebook code or mutate the analysis.

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
uv run pytest                                    # full Python suite

cd ui
npm run build                                    # TypeScript + production bundle
npm run test:e2e                                 # Playwright chat/report flows
```

The repository-wide pytest configuration uses importlib mode so plugin test modules
with matching filenames are collected independently. The end-to-end suite covers both
an independent session's Reports rail and the published report artifact flow.

### Rebuild the frontend

The frontend is built automatically on first run. To force a rebuild:

```bash
rm -rf ui/dist && uv run dataclaw
```

### Sync OpenClaw tool manifest

The bridge plugin's tool manifest (`openclaw.plugin.json contracts.tools` + `src/tools/tool-manifest.generated.ts`) is regenerated automatically every time you click **Install** on the OpenClaw Bridge — the install service snapshots the live tool registry at install time. Add a new tool, watch the drift banner appear on the Config / Tools pages, click Install, then check the sync status. A healthy status has equal live and installed counts with no added or removed entries.

Do not use `openclaw plugins install` directly to refresh this bridge: it can
copy an older generated manifest without the current Dataclaw tool parameters.
Use the Dataclaw install flow below, which validates the governed report
publish contract before it updates OpenClaw.

If the Dataclaw API is running, invoke the same flow through the UI endpoint:

```bash
curl -X POST http://localhost:8000/api/openclaw/plugins/dataclaw/install
```

For a local shell sync without starting the API, use the equivalent guarded
utility:

```bash
.venv/bin/python scripts/sync_openclaw_plugin.py
```

---

## Tech Stack

**Backend:** Python 3.12+, FastAPI, LangGraph, LangChain, DuckDB, MLflow, uv

**Frontend:** React 19, TypeScript, Vite, Ant Design

**Protocol:** [AG-UI](https://docs.ag-ui.com) (Server-Sent Events)

**Agent Backends:** OpenClaw (recommended), Anthropic Claude, OpenAI, OpenAI Codex (OAuth or API key), Google Gemini, Mock

**Sub-agents:** built-in LLM (including the Release 3 analysis reviewer), browser-use, Codex

---

## License

MIT
