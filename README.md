# Dataclaw Agent

A local-first, extensible data science agent. Dataclaw provides an event-loop agent architecture with swappable providers, a hook-based plugin system, and a clean React frontend — all wired together with the [AG-UI protocol](https://docs.ag-ui.com) for standardized agent-to-UI communication.

Its built on the current opensource tools, Dataclaw = Openclaw+ Gbrain from Gary tan + Andrej Karpathy- Auto research + A custom harness layer that handles analytics and specific data science tasks. Its an experimental Beta release. This is mostly built with AI.

***A few things that would be great additions in near future will be - Nvidia open shell to make it more secure, A sub agent which can review the v1 analysis and provide feedback for improvement (its manaual now), would be good to add a hermes version to see if thats more stable vs open claw, a defined auto research skill - that runs expeiremnts on existing projects. - collaborations are welcome.

> **Local use only.** Dataclaw is designed to run on your local machine or a trusted private server. It allows arbitrary code execution (shell commands, Python notebooks) on the host device. API keys and credentials are stored as plain text in `~/.dataclaw/dataclaw.config.json`. Do not expose Dataclaw to the public internet without additional security measures.


https://github.com/user-attachments/assets/25dc8181-bd14-41ad-a81c-5f9fe108e30a

---

## Release 4 — Hermes runtime and runtime-safe orchestration

Release 4 adds Hermes Agent as a first-class runtime alongside Dataclaw and OpenClaw. Dataclaw remains the product and governance surface — it owns conversation history, enabled tools, hooks, guardrails, approvals, persistence, and run visibility — while Hermes can own the selected agent loop without depending on OpenClaw.

### Capabilities

| Area | Capability |
|---|---|
| Runtime selection | Separates the primary agent runtime (`agent.runtime`) from Dataclaw's shared utility model (`llm.backend`). Dataclaw, Hermes, and OpenClaw can now use the same utility provider for compaction and delegated sub-agents while Hermes and OpenClaw keep their own primary models. Legacy combined runtime/provider settings are migrated automatically. |
| Runtime isolation | Centralizes provider selection in immutable runtime bundles. Each run keeps the agent, utility model, compaction, tools, sub-agent registry, memory, skills, and hooks it started with, so a configuration reload cannot mix old and new providers mid-turn. A failed reload keeps the last working bundle active and exposes the configured-versus-active mismatch. |
| Hermes integration | Adds an independently installable Dataclaw adapter and Hermes extension targeting `hermes-agent==0.19.0`. A restricted Hermes profile exposes only Dataclaw tool dispatch and tool search; the integration does not import, invoke, or require OpenClaw. |
| Governed tools | Hermes tool calls are rechecked against session and project scope, then pass through Dataclaw's existing hooks, guardrails, user approval, event emission, and message persistence. Stable run and tool-call correlation, serialized callbacks, and idempotent retries prevent a callback from attaching to the wrong run or executing the same call twice. |
| Runs and recovery | Adds durable external-runtime correlation and structured `queued`, `running`, `waiting_approval`, `stopping`, `completed`, `failed`, and `cancelled` handling. One chat-router terminalization path ensures that successful assistant output is persisted once and duplicate terminal signals are ignored. |
| Approvals | Approval requests are recorded as pending session actions and restored in the chat UI after a page refresh or stream reconnect. The composer pauses while a decision is required, while Stop remains available; approval feedback is returned to the agent when a request is denied. |
| Configuration and operations | Reworks the Agent configuration surface around separate **Utility model** and **Agent runtime** choices, with configured/active runtime status, Hermes install and extension setup, API health, model configuration, restart controls, and actionable authentication errors. |
| Evaluation | Adds a non-gating Hermes native batch-evaluation command with machine-readable summaries for model and tool baselines. Governed tool, approval, and Runs behavior remains covered by the adapter integration tests. |

### Hermes setup

Hermes runs in its own compatible environment. Install the pinned API-server build, then use the Config page to create the restricted `dataclaw` profile, install the bundled extension, authenticate the Hermes primary model, and select **Hermes Agent** as the runtime:

```bash
uv tool install --python 3.12 'hermes-agent[messaging]==0.19.0'
```

Configure a Dataclaw utility provider separately. Hermes 0.19's chat endpoint runs a complete server-side agent and does not provide the raw continuation contract needed by Dataclaw compaction and delegated sub-agents.

See the [Hermes runtime plan](docs/hermes-runtime-plan.md), [implementation contract](docs/hermes-runtime-implementation-spec.md), and [adapter guide](plugins/dataclaw-hermes/README.md) for architecture, configuration, diagnostics, and evaluation details.

### Release scope

- Hermes mode is implemented against the pinned `hermes-agent==0.19.0` source contract. Live compatibility capture for streaming, approvals, cancellation, reconnects, correlation, and batch execution remains a release gate before treating the integration as production-ready.
- Approval waits and live event streams are process-local. They can survive a browser refresh, but not a Dataclaw or Hermes process restart; cross-restart approval recovery and event replay are deferred.
- Release 4 reuses Dataclaw's existing `delegate_to_subagent` tool. Hermes-native delegation, persistent goals, long-term memory, scheduled/background work, multiple profiles, and per-session runtime pinning are not included.
- The integration preserves Dataclaw's local/private trust model and adds no authentication, TLS, sandbox, or multi-user boundary. Hermes callback routes are unauthenticated, so keep Dataclaw and Hermes on loopback or a trusted private network.

## Release 3 — governed analysis and reporting

Release 3 adds an evidence-backed path from exploratory analysis to a reviewed, versioned report, together with a redesigned session workspace, a reworked reporting layer, a rebuilt configuration surface, and live run feedback. The governance model runs throughout: claims trace back to evidence, and publication is gated on the required reviews.

### Capabilities

| Area | Capability |
|---|---|
| Analysis | Adds a durable EDA ledger for hypotheses, findings, validation state, and notebook or structured-evidence anchors. Readiness checks now make unresolved data-quality and validation gaps visible before downstream work. |
| Review and plans | Adds stable plan-step IDs, deterministic analysis-review checklists, validation gates, and an audited path for user-approved risk acceptance. A required sub-agent review remains unresolved until that reviewer has actually run. |
| Reports | Generates one handcrafted, evidence-bound HTML document per report: an LLM authors the prose, story, layout, original CSS, and bespoke SVG/Canvas visuals from a lean evidence-and-requirements storyboard. Every substantive claim and quantitative visual binds to its source or evidence alias, and methodology, limitations, and source coverage are tracked and gated. Authoring runs a validate → evidence-review → bounded-repair loop; a versioned rubric keeps every evidence and integrity gate; analytical and authoring-rigor reviews gate publication, with design/story review an author-owned stub. Reports are desktop-oriented, contrast-checked, and served as sandboxed artifacts with working in-document navigation; provenance and compaction boundaries are hardened so evidence and summary edges stay intact. Browser-based visual review runs when required, and publish receipts plus optional DOCX export remain. |
| Authoring performance | Reasoning-effort control now takes effect on all direct backends (Anthropic, OpenAI, Gemini), not just Codex. Authoring defaults to medium reasoning effort for stronger prose, story, and visual design, with a per-report knob to raise or lower it; transient stream drops during a long author run are retried. |
| Artifacts | Adds session-scoped HTML publication with validation, immutable version history, revision conflict checks, export, living-report notes, and sandboxed previews. Structured reports must have a current successful `report_publish` receipt before they can become an artifact version. |
| Configuration | A redesigned Config page with a server-side authenticated model catalog — validate a newly entered key and pick a model before saving, while stored credentials stay masked. Conversation history is now counted and compacted by complete turns rather than by raw messages. |
| Chat | The transcript streams live tool progress and run health during a turn, so long-running tools and stalled runs are visible as they happen. |
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
| `dataclaw-workspace` (expanded) | Design storyboard-backed reports as handcrafted evidence-bound documents, capture visual-review evidence, and create hash-bound publish receipts. |
| `dataclaw-plans` (expanded) | Track stable plan-step identity, validation readiness, gate state, and explicitly approved risk acceptance. |
| `dataclaw-notebooks` (expanded) | Emits first-class metric output and improves isolated-kernel Python resolution. |

### Skill library

- Governed workflow skills: `structured_eda`, `survey_analytics`, `segmentation`, `insight_validation`, `analysis_review`, `report_design`, `artifacts`, and `visualization`, alongside the `dataclaw_data_science` router (in `dataclaw.md`) and the compact `data_profiling`, `notebook_report`, and `sql_analyst` paths.
- The reporting and analysis skills — `report_design`, `structured_eda`, `visualization`, `artifacts`, and `dataclaw_data_science` — are tuned for the governed workflow, and the standalone `dashboarding` skill is retired, its guidance folded into `report_design` and `visualization`.
- Skills are installed from `skill-library/`. OpenClaw tool-manifest installation and skill synchronization are separate operations.

### Release scope

- Release 3 remains an experimental beta for local machines and trusted private servers.
- Artifact versions and review records are stored by the local Dataclaw instance; this release does not add public hosting, authentication, or multi-user permissions.
- Generic hand-authored HTML can use the artifact validator directly. Storyboard-backed structured reports have the stricter review-and-receipt publication path described above.

### Visual report example

The World Cup 2026 forecast shows the governed analysis-to-report workflow rendered as one complete, handcrafted document. The snapshots below are sections of that single report: a decision-first hero, evidence-bound figures with their interpretation beside them, a sensitivity view, and explicit data-quality limits.

![Decision-first hero — "Spain has the shortest path" — with the selected-model title probability called out.](examples/Fifa%20WC%2026/snapshots/hero.png)

![Champion probabilities as an evidence-bound bar chart, with its denominator and an interpretation reading the result as conditional, not certain.](examples/Fifa%20WC%2026/snapshots/champion-probabilities.png)

![Model-sensitivity range plot — champion-probability spread across four specifications, with the 50% line marked.](examples/Fifa%20WC%2026/snapshots/model-sensitivity.png)

![Data-quality audit — fixture-integrity tiles, result and status distributions, and a reconciliation count table.](examples/Fifa%20WC%2026/snapshots/data-quality.png)

**[Open the standalone HTML report](examples/Fifa%20WC%2026/art-48c8874a-v1.html)** · [Source notebook](examples/Fifa%20WC%2026/fifa_wc_26.ipynb)

> These are excerpts. GitHub renders the HTML file as source, so after cloning the repository open it locally in a browser for the full report.

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

Because Dataclaw listens on the container interface, the API requires an access token (see [Access control](#access-control)). On first start the server logs a one-time login URL; the token is also stored in `${DOCKER_DATA_DIR:-./docker-data}/dataclaw/api-token`. The port is published on the host's loopback interface only; set `DATACLAW_PUBLISH_ADDR=0.0.0.0` to reach it from other machines.

| | |
|---|---|
| **Port** | `8000` — Dataclaw UI and API |
| **Volumes** | `${DOCKER_DATA_DIR:-./docker-data}/dataclaw` — Dataclaw config, sessions, workspaces |

### Option 3: Docker — Bundled with OpenClaw

For the full experience with OpenClaw as the agent runtime:

```bash
docker compose -f docker-compose.bundled.yml up --build
```

This builds a single container with both Dataclaw and OpenClaw pre-installed. On first start it bootstraps the OpenClaw gateway, installs the `dataclaw` plugin, and generates the gateway token and the Dataclaw access token. All state persists under `docker-data/`.

The Dataclaw API requires the access token in this setup. On first start the container log prints a login URL (`http://localhost:8000/?token=...`); the token is kept in `${DOCKER_DATA_DIR:-./docker-data}/dataclaw/api-token` (`docker compose -f docker-compose.bundled.yml exec dataclaw cat /root/.dataclaw/api-token`). Set `DATACLAW_TOKEN` to choose your own. All ports are published on the host's loopback interface only; set `DATACLAW_PUBLISH_ADDR=0.0.0.0` to expose them on your network.

**Supported OpenClaw version: 2026.10.7.** The image pins `OPENCLAW_VERSION=2026.10.7` (Node 24.22.1), and the `dataclaw` plugin declares `minHostVersion >=2026.10.7`, so plugin installs refuse older OpenClaw releases (including `extended-stable` 2026.9.x).

**First-run setup:**

1. Start the container — it will bootstrap OpenClaw automatically
2. Open the login URL from the container log (or http://localhost:8000 and paste the access token), then go to http://localhost:8000/config
3. Click **Configure Model** to authenticate your model provider through the embedded terminal — when you close the modal a popup will remind you to restart OpenClaw so the new model takes effect (`openclaw gateway restart`, or restart the container)
4. Start using Dataclaw at http://localhost:8000

For full OpenClaw onboarding beyond the model provider, use the integrated terminal in the Dataclaw UI or `docker exec -it <container> bash`.

#### OpenClaw + OpenRouter

OpenClaw ships a built-in `openrouter` provider, and Dataclaw can configure it so the OpenClaw agent runs on any OpenRouter model. This covers the OpenClaw runtime only. Dataclaw's own utility model is configured separately.

- **UI:** on **Config → Agent → OpenClaw → Model provider**, choose **OpenRouter**, paste an API key, choose a model, and set the privacy options if you want them: *Don't route to providers that store data* (`data_collection: "deny"`), *Require zero data retention* (`zdr`), and a provider sort. **Apply to OpenClaw** takes effect without a gateway restart. Choose *Other provider* to keep the terminal sign-in (`openclaw models auth login`).
- **Bundled image:** set `OPENROUTER_API_KEY` (and optionally `DATACLAW_OPENCLAW_MODEL`, e.g. `openrouter/anthropic/claude-opus-5.5`) in `.env` or the environment. At start, the key is stored in OpenClaw only when it has no OpenRouter credential yet, so it never replaces a key set in the UI. The model is applied on every start. With only a key and no configured model, the model defaults to `openrouter/auto`.
- **API:** `POST /api/openclaw/model` with `{"provider": "openrouter", "api_key": "…", "model": "openrouter/<vendor>/<model>", "routing": {"data_collection": "deny", "zdr": true, "sort": "price"}, "response_cache": {"enabled": true, "ttl_seconds": 300}}`. Every field except `provider` and `model` is optional. An `api_key` in the request replaces OpenClaw's existing key. Without one, the request uses `OPENROUTER_API_KEY` from Dataclaw's environment only if OpenClaw has no OpenRouter credential yet, so a save never replaces an OAuth sign-in or a key pasted earlier. The response's `key_source` (`request`, `env` or `existing`) says which happened. `GET /api/openclaw/model` reports the primary model, the routing settings and `configured` (whether a key exists; the key itself is never returned). `GET /api/openclaw/openrouter/models` is a cached proxy of OpenRouter's public model list.

The key is piped to `openclaw models auth paste-api-key --provider openrouter` on stdin, so it never appears on a command line, in Dataclaw's logs or in its API responses. It lives in OpenClaw's credential store (`~/.openclaw/state/openclaw.sqlite`), not in `openclaw.json`. The model is set with `openclaw models set`, and routing and cache settings go to `agents.defaults.models["<ref>"].params`. When the model changes, the previous model's entry there is removed in the same write, but only if it is empty or holds nothing but those settings. Entries with an alias, a runtime pin, other params, or a place in the fallback list are kept.

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
2. Click **Install OpenClaw** and follow the prompts (this installs OpenClaw 2026.10.7, the supported version; an existing install must be 2026.10.7 or newer, which needs Node `>=24.22.1 <25` or `>=26.12.1`)
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

Clicking **Install** is also your consent to the plugin's declared OpenClaw capabilities (the `dataclaw` channel, its tools, and its bundled skills): the installer passes `--accept-capabilities` and logs the accepted surface. OpenClaw asks again whenever that surface grows, e.g. after you add a tool, which the next Install covers. Skills synced from the Skills page are written to OpenClaw's managed skills directory (`~/.openclaw/skills/`), so plugin reinstalls don't remove them.

### 3. Create a Project

Navigate to **Projects** in the sidebar and create a new project. Each project gets:
- An isolated Python environment for notebooks
- A dedicated file workspace
- MLflow experiment tracking
- Scoped chat sessions

### 4. Install the analysis and reporting skills you need

Open **Skills** to browse the bundled Skill Library. For the governed Release 3 path, install `structured_eda`, `insight_validation`, and `analysis_review`; add `survey_analytics` for designed-sample survey, poll, questionnaire, panel, or survey-verbatim work; add `segmentation` for grouping a population into decision-serving segments, personas, or value/risk tiers; add `report_design` and `artifacts` when the session will publish a report or report-like dashboard, and add `visualization` when notebook charting or visual-evidence preparation is needed.

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

Core: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `pyyaml`, `openai`, `langgraph`, `langchain-core`, `ag-ui-protocol`

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
| `dataclaw-workspace` | 9 (file I/O, shell exec, report design/review/publish) | — | dataclaw-artifacts, html-for-docx, PyYAML |
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

Notebook dataset reads are authorized against the active chat session. Omitting
`n_rows` streams the full result as Parquet; passing `n_rows` requests a preview
capped by `plugins.data.max_notebook_rows` (default `10000`). For large datasets,
prefer selective SQL over loading an entire wide table. DataFrames expose
`df.attrs["dataclaw_access_mode"]`, `df.attrs["dataclaw_truncated"]`, and
`df.attrs["dataclaw_row_limit"]`.

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

browser-use's anonymized PostHog telemetry is turned off by default. The browser plugin starts browser-use's telemetry with `ANONYMIZED_TELEMETRY=false` and then restores the environment, so the setting doesn't leak into other code or child processes. To opt in, set `ANONYMIZED_TELEMETRY=true` before starting DataClaw.

Subagent definitions are managed in the **Subagents** page (`/subagents`) and can be scoped per-project. The parent agent's `list_subagents` tool returns only the subagents the current session has been allowed to use.

### Custom Tools & MCP Servers

The `dataclaw-custom-tools` plugin lets you extend the tool surface without touching the codebase:

- **Custom Python tools** — drop a `.py` file under `~/.dataclaw/tools/` exporting a `tool_definition` dict + a callable. They're loaded at startup and on hot-reload (`POST /api/custom-tools/reload`).
- **MCP servers** — register an [MCP](https://modelcontextprotocol.io/) server (stdio or HTTP) from the **Tools** page; its tools are auto-discovered and exposed under the same registry the agent loop uses.

Adding or removing tools triggers a drift banner on the OpenClaw bridge install card so you know to re-install the bridge plugin (or click the bundled image's auto-install) to refresh the manifest in OpenClaw.

### Kaggle Integration

The `dataclaw-kaggle` plugin wires up the Kaggle API end-to-end. Configure the
token from Kaggle's **Generate New Token** flow on the Config page
(`plugins.kaggle.kaggle_api_token`). Legacy `kaggle.json` username + key
credentials remain supported through `plugins.kaggle.kaggle_username` and
`plugins.kaggle.kaggle_key`. The agent then gets:

- `list_competitions`, `competition_details`, `leaderboard`, `download_competition`
- `search_datasets`, `download_dataset`
- `submit`, `submissions`

Downloaded competition/dataset archives can be auto-registered as Dataclaw datasets when `auto_register_datasets` is on (default), so the agent can immediately profile and query them.

---

## Configuration

All runtime data under `~/.dataclaw/` (override with `$DATACLAW_HOME`):

```
~/.dataclaw/
  dataclaw.config.json     # Main config (credentials stored as plain text, mode 0600)
  api-token                # Generated API access token (mode 0600)
  sessions/                # Chat session JSON files
  skills/                  # Skill markdown files
  workspaces/              # Per-workspace file storage + notebooks
  plugins/                 # Plugin data (datasets, plans, EDA, reviews, artifacts, venvs, etc.)
```

### Environment Variables

| Variable | Config path | Default |
|---|---|---|
| `DATACLAW_AGENT_RUNTIME` | `agent.runtime` | `openclaw` |
| `DATACLAW_UTILITY_BACKEND` | `llm.backend` | `codex` |
| `DATACLAW_LLM_BACKEND` | Legacy combined runtime/provider override | |
| `ANTHROPIC_API_KEY` | `llm.backends.anthropic.api_key` | |
| `ANTHROPIC_MODEL` | `llm.backends.anthropic.model` | `claude-opus-5-5` (utility: `claude-haiku-5-5`) |
| `OPENAI_API_KEY` | `llm.backends.openai.api_key` / `llm.backends.codex.api_key` | |
| `OPENAI_MODEL` | `llm.backends.openai.model` | `gpt-6.1-sol` (utility: `gpt-6-luna`) |
| `OPENAI_BASE_URL` | `llm.backends.openai.base_url` | `https://api.openai.com/v1` |
| `GOOGLE_API_KEY` | `llm.backends.gemini.api_key` | |
| `GEMINI_MODEL` | `llm.backends.gemini.model` | `gemini-4-argon` (utility: `gemini-3.8-flash`) |
| `CODEX_MODEL` | `llm.backends.codex.model` | `gpt-5.5` |
| `CODEX_AUTH_MODE` | `llm.backends.codex.auth_mode` | `default` (OAuth) — `api_key` for direct |
| `DATACLAW_MAX_TURNS` | `app.max_turns` | `30` |
| `DATACLAW_HOST` | `app.host` | `127.0.0.1` |
| `DATACLAW_PORT` | `app.port` | `8000` |
| `DATACLAW_TOKEN` | `app.token` | Generated into `~/.dataclaw/api-token` |
| `DATACLAW_AUTH` | `app.auth` | `auto` — token required for non-loopback binds; `token` — always |
| `DATACLAW_ALLOWED_ORIGINS` | `app.allowed_origins` | Extra browser origins (comma-separated) |
| `DATACLAW_ALLOWED_HOSTS` | `app.allowed_hosts` | Extra `Host` names accepted on a loopback bind |
| `DATACLAW_OPENCLAW_URL` | `plugins.openclaw.url` | `http://127.0.0.1:18789` |
| `KAGGLE_API_TOKEN` | `plugins.kaggle.kaggle_api_token` | |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | `plugins.kaggle.kaggle_username` / `plugins.kaggle.kaggle_key` | Legacy credentials |

### LLM backends

`llm.backend` selects the utility model backend; each backend's settings live
under `llm.backends.<id>` (`api_key`, `base_url`, `model`, `headers`, `preset`,
`reasoning_effort`, and `api` for `openai`). Configs that still use the older
`llm.anthropic|openai|gemini|codex` sections are migrated on startup. Before
the first change, the original file is saved once as
`~/.dataclaw/dataclaw.config.json.pre-llm-backends.bak` (mode 0600, never
overwritten); restore it if you downgrade. Models that were the old defaults
move to the same tier: `claude-sonnet-4-20250514` → `claude-sonnet-5-5`,
`gpt-4o` → `gpt-6.1-sol` (unless a custom `base_url` is set), and
`gemini-2.5-flash` → `gemini-3.8-flash`. Fresh installs use the defaults in the environment-variable table
above.

| Backend | Transport | Notes |
|---|---|---|
| `anthropic` | Messages API (langchain-anthropic) | Effort via `output_config.effort` |
| `openai` | Responses API (`store=false`) | Set `api: "chat_completions"` to opt out; a custom `base_url` defaults to Chat Completions |
| `gemini` | langchain-google-genai | `thinking_level` |
| `codex` | Responses API via Codex OAuth or an API key | |
| `openai_compatible` | Chat Completions at a custom `base_url` | Presets: Ollama, vLLM, LM Studio (keyless), OpenRouter, Groq, xAI, DeepSeek, Mistral, Together |
| `open_responses` | Responses API at a custom `base_url` | For [Open Responses](https://www.openresponses.org) servers; API key optional |

A backend that needs an API key and has none fails with a configuration error
naming the env var and config path; the runtime status in Settings shows it.
Hosted presets also read their own key variable (`OPENROUTER_API_KEY`,
`GROQ_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`,
`TOGETHER_API_KEY`). vLLM's default port (8000) clashes with DataClaw's, so its
preset expects `--port 8001`. Plugins can add backends with
`PluginContext.register_llm_backend`.

Changes to the agent runtime, the DataClaw utility model, and supported plugin
integrations are **hot-reloaded** — no server restart needed. The utility model
is shared by DataClaw, Hermes, and OpenClaw for compaction and delegated
sub-agents. When `agent.runtime` is `dataclaw`, the same model also runs the
primary agent.

### Decision models

A decision model answers typed questions about a state instead of chatting:
`choice` (pick one option), `score` (ordered levels; the answer is the
expected level) and `boolean` (yes/no), each with a confidence and, where the
backend has one, a probability distribution. Settings live under `decision`:

| Key | Env | Default | Notes |
|---|---|---|---|
| `decision.backend` | `DATACLAW_DECISION_BACKEND` | `none` | `typesafe`, `llm` or a plugin backend |
| `decision.typesafe.api_key` | `TYPESAFE_API_KEY` | | TypeSafe or Vercel AI Gateway key |
| `decision.typesafe.model` | | `jev-latest` | `jev-preview`, `jev-1.14.0`, `jev-1.13.0` |
| `decision.typesafe.base_url` | | `https://api.typesafe.ai` | `https://ai-gateway.vercel.sh/typesafe` for Vercel AI Gateway |
| `decision.min_confidence` | `DATACLAW_DECISION_MIN_CONFIDENCE` | `0.7` | |
| `decision.routing.{plan_gates, skill_routing, compaction}` | | `false` | Opt-in internal uses |

- **`typesafe`** calls TypeSafe's [Jev](https://docs.typesafe.ai/models)
  (`POST /v1/systemone`), retrying 429/529/5xx with backoff. State beyond
  Jev's limits (64k tokens per request, 32k per question) is truncated with a
  logged warning.
- **`llm`** answers the same questions with the utility model through
  structured output. Its confidence is the model's own estimate, so results
  are marked `calibrated: false` and carry no probabilities.

With a backend selected, the agent gets a **`decide`** tool (also exposed to
OpenClaw and Hermes). It falls back to the utility LLM when Jev is
unavailable. The routing toggles are advisory and fall back to the LLM when
Jev fails or answers below `min_confidence`:

- `plan_gates` adds a `decision_precheck` gate (`pass` or `warn`) to plan
  steps with recorded work. It blocks only if a stored gate policy marks it
  required.
- `skill_routing` adds a "likely playbook" hint to the prompt while a plan is
  being drafted.
- `compaction` can compact history early, once it reaches half of a
  threshold. It never skips a compaction the thresholds require.

`skill_routing` and `compaction` apply only when DataClaw runs the agent loop.
Each decision is logged and emitted as a `decision:result` event on the run
stream. Plugins can add backends with
`PluginContext.register_decision_backend`.

---

## Security Considerations

Dataclaw is intended for **local/private use only**:

- **Code execution**: The workspace plugin runs arbitrary shell commands. The notebook plugin executes arbitrary Python. Both run with the permissions of the host process.
- **Credential storage**: API keys, tokens, and connection strings are stored as plain text in `~/.dataclaw/dataclaw.config.json`.
- **Access control**: see [Access control](#access-control). On the default loopback bind the API has no login; anyone who can run code as a local user can reach it.
- **Dataset queries**: SQL queries are restricted to read-only (SELECT/WITH/SHOW), but the shell execution tool has no such restriction.
- **Network binding**: Direct `uv run dataclaw` starts on `127.0.0.1` by default. The Docker configurations listen on the container interface (so the access token is required) and publish their ports on the host's loopback interface unless `DATACLAW_PUBLISH_ADDR` says otherwise.
- **HTML output**: Raw workspace HTML and SVG are downloaded rather than executed at the app origin. Intentional HTML previews and published artifacts run in sandboxed frames with restrictive CSP and no network egress, but this does not sandbox shell or notebook execution.

Do not expose Dataclaw to untrusted networks without TLS and sandboxing.

### Access control

- **Origin and Host checks (always on).** WebSocket handshakes (including the terminal) and state-changing requests are rejected when their `Origin` is not the app's own origin, one of the built-in development origins, or listed in `DATACLAW_ALLOWED_ORIGINS`. Requests without an `Origin` header (CLI tools, integrations) are unaffected. On a loopback bind the `Host` header must be a loopback name (`localhost`, `127.0.0.1`, `[::1]`, `*.localhost`) or listed in `DATACLAW_ALLOWED_HOSTS`.
- **Access token.** Required whenever `DATACLAW_HOST` is not a loopback address (and on loopback when `DATACLAW_AUTH=token`). The token is `DATACLAW_TOKEN` / `app.token` when set; otherwise one is generated on first start into `~/.dataclaw/api-token` (mode 0600) and the server logs a login URL. Browsers log in once via `/?token=...` or the token prompt and then use an HttpOnly, SameSite=Strict cookie. Scripts send `Authorization: Bearer <token>` or `X-Dataclaw-Token: <token>`. `/api/health` stays open.
- **Integrations.** The same token is the shared secret with the OpenClaw `dataclaw` plugin (sent in both directions), the Hermes extension and notebook kernels. After changing the token, reinstall the OpenClaw plugin and the Hermes extension from the Config page.
- **Config files.** `dataclaw.config.json`, `mcp-servers.json` and the token file are written atomically with mode 0600.

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

**Agent Backends:** OpenClaw (recommended), Anthropic Claude, OpenAI, OpenAI Codex (OAuth or API key), Google Gemini, OpenAI-compatible endpoints, Open Responses endpoints, Mock

**Sub-agents:** built-in LLM, browser-use, Codex

---

## License

MIT
