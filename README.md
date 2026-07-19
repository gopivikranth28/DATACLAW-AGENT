# Dataclaw Agent

A local-first, extensible data science agent. Dataclaw provides an event-loop agent architecture with swappable providers, a hook-based plugin system, and a clean React frontend — all wired together with the [AG-UI protocol](https://docs.ag-ui.com) for standardized agent-to-UI communication.

Its built on the current opensource tools, Dataclaw = Openclaw+ Gbrain from Gary tan + Andrej Karpathy- Auto research + A custom harness layer that handles analytics and specific data science tasks. Its an experimental Beta release. This is mostly built with AI.

***A few things that would be great additions in near future will be - Nvidia open shell to make it more secure, A sub agent which can review the v1 analysis and provide feedback for improvement (its manaual now), would be good to add a hermes version to see if thats more stable vs open claw, a defined auto research skill - that runs expeiremnts on existing projects. - collaborations are welcome.

> **Local use only.** Dataclaw is designed to run on your local machine or a trusted private server. It allows arbitrary code execution (shell commands, Python notebooks) on the host device. API keys and credentials are stored as plain text in `~/.dataclaw/dataclaw.config.json`. Do not expose Dataclaw to the public internet without additional security measures.


https://github.com/user-attachments/assets/25dc8181-bd14-41ad-a81c-5f9fe108e30a

---

## Release 3 — governed analysis and reporting

Release 3 is the next major branch after `main`. It adds an evidence-backed path from exploratory analysis to a reviewed, versioned report, together with a redesigned session workspace.

[Compare `release3` with `main`](https://github.com/gopivikranth28/DATACLAW-AGENT/compare/main...release3)

### What changed from `main`

| Area | Release 3 change |
|---|---|
| Analysis | Adds a durable EDA ledger for hypotheses, findings, validation state, and notebook or structured-evidence anchors. Readiness checks now make unresolved data-quality and validation gaps visible before downstream work. |
| Review and plans | Adds stable plan-step IDs, deterministic analysis-review checklists, validation gates, and an audited path for user-approved risk acceptance. A required sub-agent review remains unresolved until that reviewer has actually run. |
| Reports | Adds storyboard-first HTML composition, a versioned report rubric, design and analytical review, optional runtime visual authoring, browser-based visual review when required, publish receipts, and optional DOCX export. |
| Artifacts | Adds session-scoped HTML publication with validation, immutable version history, revision conflict checks, export, living-report notes, and sandboxed previews. Structured reports must have a current successful `report_publish` receipt before they can become an artifact version. |
| OpenClaw | Expands the bridge to snapshot the live Dataclaw tool manifest, validate the governed reporting toolchain, and surface manifest drift when the plugin needs to be reinstalled. |
| Reliability and safety | Fixes project-kernel Python resolution, isolates independent and project sessions, tightens workspace path handling, serves workspace HTML/SVG as attachments by default, and adds CSP-constrained HTML previews. |

### UI updates

- **Session-centric Chat.** Independent chats and project-scoped sessions have separate directories and workspace context. New independent chats confirm dataset scope before creation; project sessions inherit their project context.
- **A persistent session rail.** Plans, Files, Reports, Datasets, Experiments, and Scope are available without crowding the transcript. The plan pill and rail badges surface work that needs attention.
- **Calmer run activity.** Operational tool calls are grouped into expandable per-turn activity, while metrics, Plotly charts, tables, and other evidence remain visible in the conversation with their notebook provenance.
- **In-thread queueing.** Messages sent during a run are queued in order and can be edited, removed, promoted, paused, or resumed. Plan approval and feedback stay beside the composer.
- **Report review in place.** The Reports panel separates published versions from scratch drafts, shows counts and version controls, previews the selected report, and provides open/export actions. The compatibility App view remains available at `/app/<session-id>` for loose metrics and charts.
- **Reworked Skills page.** A two-column master–detail view separates **My Skills** from the **Skill Library**, labels custom and library-installed skills, supports inline installation, and keeps skill creation, Markdown import, editing, and export in one place.

### Typical Release 3 workflow

1. **Explore** with `structured_eda`, recording hypotheses and findings against notebook or structured evidence.
2. **Validate** material claims with `insight_validation` and summarize whether the dataset is ready for its intended use.
3. **Review** high-risk or EDA-like plan steps with `request_analysis_review`; resolve findings or obtain explicit user approval to accept a documented risk.
4. **Design** the final report with `report_design_report`, then complete any required visual review with `report_review_visuals`.
5. **Publish** the exact reviewed HTML with `report_publish`, then create or revise its versioned artifact with `publish_artifact`.

This chain improves traceability from a published claim back to its evidence and review record. It is a governance aid, not a guarantee that an analysis is correct.

### New and expanded plugins

| Area | Release 3 tool surface |
|---|---|
| `dataclaw-eda` (new) | Propose and update hypotheses; record, read, list, and supersede findings; summarize EDA readiness. |
| `dataclaw-analysis-review` (new) | Request reviews, list review runs and findings, resolve findings, and inspect the review gate for plan steps, artifacts, living reports, or sessions. |
| `dataclaw-artifacts` (new) | Publish, read, list, export, revise, and delete versioned HTML artifacts; append living-report notes. |
| `dataclaw-workspace` (expanded) | Build or design storyboard-backed reports, add draft sections, capture visual-review evidence, and create hash-bound publish receipts. |
| `dataclaw-plans` (expanded) | Track stable plan-step identity, validation readiness, gate state, and explicitly approved risk acceptance. |
| `dataclaw-notebooks` (expanded) | Emits first-class metric output and improves isolated-kernel Python resolution. |

### Skill library additions

- Added: `analysis_review`, `artifacts`, `dashboarding`, `insight_validation`, `report_design`, `structured_eda`, and `visualization`.
- Updated: `dataclaw_data_science` now routes governed EDA, review, report, and artifact work; `data_profiling` remains the compact profiling path.
- Skills are installed from `skill-library/`. OpenClaw tool-manifest installation and skill synchronization are separate operations.

### Release scope

- Release 3 remains an experimental beta for local machines and trusted private servers.
- Artifact versions and review records are stored by the local Dataclaw instance; this release does not add public hosting, authentication, or multi-user permissions.
- Generic hand-authored HTML can use the artifact validator directly. Storyboard-backed structured reports have the stricter review-and-receipt publication path described above.

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

Create a `.env` file so Dataclaw listens on the container interface. Provider keys can be added to the same file:

```dotenv
DATACLAW_HOST=0.0.0.0
ANTHROPIC_API_KEY=sk-...
```

```bash
docker compose up --build
```

This builds and runs Dataclaw in a container with the UI pre-built. The server starts on http://localhost:8000. You can also configure the LLM API key from the Config page.

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

### 4. Install the analysis and reporting skills you need

Open **Skills** to browse the bundled Skill Library. For the governed Release 3 path, install `structured_eda`, `insight_validation`, and `analysis_review`; add `visualization`, `dashboarding`, `report_design`, and `artifacts` when the session will publish a report or dashboard.

Installed skills become available to direct LLM sessions, subject to the project or session Scope selection. When OpenClaw is active, the Skills page also offers to synchronize each installed skill to the Dataclaw OpenClaw extension. Skill synchronization is separate from reinstalling the OpenClaw tool manifest.

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

Plugins and analytical output: `duckdb`, `nbformat`, `jupyter_client`, `mlflow`, `plotly`, `html-for-docx`, `pyyaml`, `browser-use`

All dependencies are managed by `uv` and installed automatically on first run.

### Frontend Dependencies

`react`, `antd`, `vite`, `react-router-dom`, `react-markdown`, `plotly.js-dist-min`, `react-ipynb-renderer`, and TipTap — installed via `npm install` during the frontend build. Playwright provides the report-preview and artifact-flow end-to-end tests.

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

### Governed Analysis and Report Pipeline

Release 3 adds a durable workflow around the existing agent loop:

```
Notebook analysis -> EDA ledger -> validation + analysis review -> plan gate
                  -> report storyboard + rubric -> publish receipt
                  -> versioned artifact -> Reports panel / export
```

Plugin hooks attach evidence and review state as tools run. For storyboard-backed reports, publication recomputes the current quality, design, analytical, runtime, and configured visual-review checks; the resulting receipt is bound to the exact HTML before the artifact plugin creates a version.

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
| `dataclaw-workspace` | 11 (file I/O, shell exec, report build/design/review/publish/add-section) | — | dataclaw-artifacts, html-for-docx, PyYAML |
| `dataclaw-data` | 6 (list, profile, preview, query, describe, docs) | `/api/data/*` | duckdb |
| `dataclaw-notebooks` | 14 (open, close, read, edit, execute, display_metric, etc.) | `/api/notebooks` | nbformat, jupyter_client, Plotly |
| `dataclaw-eda` | 8 (propose/update/list hypotheses, record/read/list/supersede findings, summarize readiness) | `/api/eda/*` | stdlib |
| `dataclaw-analysis-review` | 5 (request review, list/resolve findings, review gate, list runs) | `/api/analysis-review/*` | dataclaw-plans, dataclaw-eda, dataclaw-artifacts |
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
- Analysis-review, validation, and report-publication gates still apply; Auto Mode only removes the plan-proposal approval click.

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
  plugins/                 # Plugin data (datasets, plans, EDA, reviews, artifacts, venvs, etc.)
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
| `DATACLAW_HOST` | `app.host` | `127.0.0.1` |
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
- **Network binding**: Direct `uv run dataclaw` starts on `127.0.0.1` by default. The Docker configurations listen on the container interface and publish port 8000, so they should be treated as network-accessible unless the host binding or firewall restricts them.
- **HTML output**: Raw workspace HTML and SVG are downloaded rather than executed at the app origin. Intentional HTML previews and published artifacts run in sandboxed frames with restrictive CSP and no network egress, but this does not sandbox shell or notebook execution.

Do not expose Dataclaw to untrusted networks without adding authentication, TLS, and sandboxing.

---

## Development

### Run tests

```bash
uv sync --extra dev
uv run pytest tests/ -v                          # core tests
uv run pytest plugins/dataclaw-data/tests/ -v    # data plugin
uv run pytest plugins/dataclaw-notebooks/tests/  # notebooks
uv run pytest plugins/dataclaw-eda/tests/ \
  plugins/dataclaw-analysis-review/tests/ \
  plugins/dataclaw-artifacts/tests/ \
  plugins/dataclaw-workspace/tests/              # Release 3 analysis/reporting stack
npm --prefix ui run test:e2e                     # report preview + artifact flow
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

Or run the repository helper, which discovers the live tool registry, validates the report-tool contract, rebuilds the extension, and installs it through the same governed flow:

```bash
uv run python scripts/sync_openclaw_plugin.py
```

This refreshes OpenClaw's Dataclaw tools. Installed skill files are synchronized separately from the **Skills** page so local skill edits are never implied by a tool-manifest reinstall.

---

## Tech Stack

**Backend:** Python 3.12+, FastAPI, LangGraph, LangChain, DuckDB, MLflow, Plotly, uv

**Frontend:** React 19, TypeScript, Vite, Ant Design, Plotly.js, TipTap

**Protocol:** [AG-UI](https://docs.ag-ui.com) (Server-Sent Events)

**Agent Backends:** OpenClaw (recommended), Anthropic Claude, OpenAI, OpenAI Codex (OAuth or API key), Google Gemini, Mock

**Sub-agents:** built-in LLM, browser-use, Codex

---

## License

MIT
