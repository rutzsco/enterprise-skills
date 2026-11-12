# Enterprise Memory

A local, single-user hackathon demo that turns expert knowledge into reusable skills an agent can discover and load **at runtime**.

- **Demo chat:** a registered Azure / Microsoft Foundry prompt agent chooses read-only discovery and loading tools. Answers show the actual tool calls and loaded skill versions.
- **Skill library:** persistent create, edit, and delete operations for named Markdown playbooks.
- **Expert intake:** save rough SME notes, then use a Foundry authoring agent to propose new skills or updates. Review, edit, approve, or reject each proposal.
- **Runtime API:** other agents can discover lightweight metadata and load current published guidance over HTTP.

The three starter playbooks are explicitly **synthetic**, not real enterprise policies. Without Azure configuration, the library, saved notes, and runtime APIs still work. Chat and agent-assisted organization show an actionable setup state; there are **no fabricated agent replies or offline AI fallbacks**.

## Run locally

Prerequisites: **Python 3.12+** and **Node.js 24 LTS**. Azure CLI is needed only if you use `az login` for live agents.

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm run build
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The Python server serves both the built React app and the API; Node is not needed to serve an existing build.

On macOS/Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

For frontend development, run the API command above plus `npm run dev` in a second terminal. Vite serves **http://127.0.0.1:5173** and proxies `/api` to port 8000. Rebuild and restart the API when switching back to the production bundle. Use one API process/worker.

## Connect real Foundry agents

Use an **existing Microsoft Foundry project** with a deployed model that supports function calling. This app does not provision Azure infrastructure.

1. Copy `.env.example` to `.env`.
2. Set these server-side values:

   ```dotenv
   FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
   FOUNDRY_MODEL_DEPLOYMENT=<your-model-deployment-name>
   FOUNDRY_AGENT_PREFIX=enterprise-memory-demo
   ```

3. Authenticate the server identity. For local development:

   ```powershell
   az login
   ```

4. Ensure that identity can read/create agent versions, create conversations, and invoke the deployment in the project. Restart the API server after changing `.env` or authentication configuration.

The endpoint must be a **project endpoint**, not an Azure OpenAI model endpoint, a classic hub connection string, or a portal URL. Copy it from your Foundry project's overview. Both `*.ai.azure.com` and `*.services.ai.azure.com` project hosts are accepted.

Authentication uses `azure.identity.aio.DefaultAzureCredential` on the server. An appropriately configured managed identity or service principal also works through its standard credential chain. Do not put credentials in the frontend or in `VITE_*` variables, and do not commit `.env`.

The UI distinguishes **not configured**, **configured but unverified**, and a **successful real run**. Merely setting environment variables does not verify Azure access. Service/authentication failures are shown explicitly, with details in the server logs.

### Actual integration and lifecycle

The server uses the supported **Microsoft Agent Framework `RawFoundryAgentChatClient`** to run **registered Foundry prompt agents**, created through `azure-ai-projects`. The application owns the bounded tool dispatcher so every call, validation error, and returned result is observable.

The framework uses Foundry's OpenAI-compatible Responses protocol underneath. Every request carries the registered agent's **name and exact version in an `agent_reference`**, plus the same conversation ID for tool continuations and follow-ups. This is **Foundry Agent Service**, not direct OpenAI inference or a provider substitution.

- Two agents are created lazily: `<prefix>-chat` and `<prefix>-author`. Choose a prefix dedicated to this demo.
- Agent-version bindings are persisted in SQLite and reused across restarts. A changed deployment, instruction set, or tool schema gets a new binding/version. If a previously bound remote version was removed, the app recreates it.
- Service calls are bounded by **90 seconds per turn, 6 response rounds, and 12 tool calls**. Invalid calls return structured errors to the agent; exhausted, incomplete, timed-out, and failed runs never masquerade as final answers.
- Browser transcripts and local conversation handles are session-only. Handles expire after an hour of inactivity or a server restart. A failed/interrupted turn requires a new chat when continuation is unsafe.
- Creating a new chat does not erase older Azure conversation data. Remote agent versions and conversations remain in the configured Foundry project for inspection. Remove demo resources through Foundry when finished, according to your project's retention policy. Local client cleanup closes connections; it does not delete remote resources.

References: [Foundry function calling](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/function-calling), [Microsoft Agent Framework Foundry integration](https://github.com/microsoft/agent-framework/tree/main/python/packages/foundry).

## Suggested demo

1. Open **Skill library** and inspect the synthetic **Software purchasing** playbook.
2. With Foundry configured, ask: **"Who needs to approve a $6,000 annual software purchase that handles customer data?"**
3. Inspect the actual `discover_skills` / `load_skill` trace and the loaded version. Full playbooks are not injected into every prompt.
4. Open **Expert intake**, choose **Use synthetic example**, and organize the notes. The authoring agent must inspect the catalog and load an existing skill before proposing an update.
5. Review the rationale, verbatim source excerpts, missing information, and current published guidance. Edit the draft if needed and **save draft edits before approval**.
6. Before approval, check the **Runtime API**: the original published skill is unchanged. Approve the proposal, then load it again to see the new version without restarting or reindexing.
7. Ask a follow-up in chat. The agent is instructed to reload current guidance on every enterprise question, including follow-ups.

Without Azure, you can still create/edit/delete skills, save SME notes, and use the live runtime API explorer. You cannot generate genuine chat answers or proposals until Foundry is configured.

## Publication and storage rules

Default database: `data\enterprise-memory.sqlite3`. Override its path with `MEMORY_DB_PATH` if needed. The database, WAL files, local environment, and dependency folders are ignored by Git.

- Synthetic playbooks are seeded **once per database**, not whenever the library is empty. Deleting all skills does not bring them back on restart.
- Skill IDs are stable; every published edit increments `version`. Writes and deletes require the version the caller saw.
- SME notes and review drafts persist across restarts. An interrupted organization is marked failed on startup, with the original notes retained for retry.
- Agent proposals have a separate `revision` and do not enter the published skill table until explicit approval.
- Approval is transactional: publishing the skill and marking the proposal approved succeed together.
- An update records the exact skill ID and base version loaded by the authoring agent. Intervening manual edits or deletion make it stale; approval returns `409` rather than overwriting them. Reject and organize fresh notes against the current catalog.
- Duplicate published names are rejected case-insensitively. The authoring agent also searches for related skills to avoid semantic duplicates, but human review is still required.
- Source excerpts must be verbatim portions of the supplied notes. This does not mathematically prove all generated guidance is grounded; verify every rule before approving. Missing facts are called out, not silently replaced with policy guesses.
- Editing/deleting a skill does not rewrite earlier chat messages. Subsequent loads read the current database state, with `Cache-Control: no-store`.

Back up the database while the server is stopped, or use SQLite's backup facilities. Do not delete the database unless you intend to reset all local skills, notes, proposals, and cached agent bindings.

## Runtime HTTP contract

Base URL: `http://127.0.0.1:8000`. These endpoints do not depend on Azure.

| Method and route | Behavior |
| --- | --- |
| `GET /api/runtime` | Describes the discovery/load contract and the local-only boundary. |
| `GET /api/runtime/skills?query=software&limit=100` | Metadata-only discovery. Searches name, description, and category using case-insensitive keyword matching. Empty query browses the catalog. |
| `GET /api/runtime/skills/{id}` | Returns the current published skill including `guidance`, identity, and version; `404` if deleted or unknown. |

Discovery returns `{ "skills": [...], "total": N, "limit": 100 }`. Each entry contains only `id`, `name`, `description`, `category`, `version`, `created_at`, and `updated_at` - **never `guidance`**. The limit is 1-100; `total` reports all matches so consumers can detect truncation and narrow the query. This deliberately small prototype is not a large-catalog search service.

Loading adds the `guidance` Markdown string to those metadata fields. Consumers should treat the loaded version as a snapshot and load again when current policy is needed. A missing skill is an error, not empty successful guidance.

```powershell
curl.exe "http://127.0.0.1:8000/api/runtime/skills?query=software"
curl.exe "http://127.0.0.1:8000/api/runtime/skills/software-purchasing"
```

Typical consumer flow: discover a few candidates, choose relevant IDs, load only those skills, then answer with the skill names/versions and the user's facts. Skill content is knowledge, **not executable code or authorization**.

### Management, review, and chat APIs

Interactive request schemas are available at **http://127.0.0.1:8000/api/docs**; OpenAPI is at `/api/openapi.json`.

| Method and route | Purpose |
| --- | --- |
| `GET /api/status` | Configuration state, verification state, and published/pending counts. Does not probe Azure or expose credentials. |
| `GET /api/skills`, `GET /api/skills/{id}` | Metadata list / full published skill. Same store as runtime. |
| `POST /api/skills` | Publish `{name, description, category, guidance}`. |
| `PUT /api/skills/{id}` | Publish fields plus `expected_version`. |
| `DELETE /api/skills/{id}?expected_version=N` | Delete only the version the caller reviewed. |
| `POST /api/intakes` | Save `{title, notes}` locally; no AI request. |
| `GET /api/intakes`, `GET /api/intakes/{id}` | List saved notes / read notes, trace, and proposals. |
| `POST /api/intakes/{id}/organize` | Run the Foundry authoring agent and persist review-only proposals. |
| `GET /api/proposals`, `GET /api/proposals/{id}` | Read drafts and review outcomes. |
| `PUT /api/proposals/{id}` | Edit skill fields, `missing_information`, and `expected_revision`; never publishes. |
| `POST /api/proposals/{id}/approve` | Explicitly publish with `{expected_revision}`. |
| `POST /api/proposals/{id}/reject` | Reject with `{expected_revision}`; published skills are unchanged. |
| `POST /api/chat` | Send `{message, session_id?}`. Returns `answer`, `session_id`, actual `events`, and `loaded_skills`. Reuse the returned session ID for follow-ups. |

Errors use `{ "error": { "code": "...", "message": "..." }, "events": [...], "reset_required": false }`. Relevant statuses: `404` missing identity, `409` stale/conflicting state, `422` invalid input, `503` missing Foundry configuration or unavailable storage, `502` agent/service failures, and `504` turn timeout.

The agent has no management or approval HTTP tools. The chat agent can only discover and load. The authoring agent's additional `propose_skills` tool collects validated drafts; only the separate human approval API publishes them.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
npm run build
```

Tests use temporary SQLite databases and controlled service/HTTP doubles. They cover persistent edits and deletions, seed-once behavior, metadata-only discovery, fresh runtime loads, optimistic concurrency, draft isolation/approval/rejection, stale proposals, grounded source excerpts, malformed/unknown calls, follow-ups, tool budgets, timeouts, service failures, and the real framework's serialized Foundry `agent_reference` / conversation / matching call-ID contract.

**Passing these tests is not a live Azure verification.** A real Foundry-connected demonstration requires the user's project, deployment, permissions, and credentials.

## Deliberate prototype limits

React + TypeScript + Vite frontend; FastAPI + SQLite backend. No MCP server, vector database, background worker, enterprise access controls, or cloud provisioning.

Keep the server bound to `127.0.0.1`. It has **no authentication, authorization, tenant isolation, or production audit trail**. Local browser-origin and host checks are a guardrail, not an enterprise security model. Do not publish it to the internet or use real confidential SME/customer data. Chat messages, authoring notes, discovery metadata, and selected guidance are sent to the configured Azure project during live runs.