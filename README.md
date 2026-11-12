# Enterprise Memory

A hackathon MVP that turns expert knowledge into reviewed, portable skills an agent can discover and load **at runtime**. Run locally with SQLite or deploy behind private Azure ingress with private Blob Storage and Cosmos DB.

- **Demo chat:** a registered Azure / Microsoft Foundry prompt agent chooses read-only discovery and loading tools. Answers show the actual tool calls and loaded skill versions.
- **Skill library:** create/edit drafts, explicit review, immutable releases, reviewed retirement and rollback, and portable `SKILL.md` package downloads.
- **Expert intake:** save rough SME notes, then use a Foundry authoring agent to propose new skills or updates. Review, edit, approve, or reject each proposal.
- **Runtime delivery:** read-only Streamable HTTP MCP resources at `/mcp`, plus compatible REST discovery/loading endpoints. A separate Agent Framework consumer demonstrates actual MCP delivery.

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

## Run with Docker

Docker builds the React frontend and packages it with the Python API in one image.
Only Docker is required on the host; the runtime runs as a non-root user with one API worker.

```powershell
docker build -t enterprise-skills:local .
docker volume create enterprise-skills-data
docker run --rm --name enterprise-skills -p 127.0.0.1:8000:8000 --mount source=enterprise-skills-data,target=/app/data enterprise-skills:local
```

Open **http://127.0.0.1:8000**. Keep the loopback-only port mapping: this demo has no
authentication. Inside the container the server listens on `0.0.0.0:8000` so Docker
can forward traffic; this does not make it safe to expose publicly.
The image includes a process health check against `/health`; it does not probe Foundry or assert data-service readiness.

The named volume preserves skills, notes, proposals, and agent bindings across
container replacements. Do not remove it unless you intend to reset that data.
If overriding `MEMORY_DB_PATH`, mount persistent writable storage at that path;
bind-mounted directories must be writable by container UID/GID `10001`.
Environment files, local databases, Git metadata, and infrastructure files are
excluded from the build context.

To enable Foundry, copy `.env.example` to `.env`, configure the project and model,
and add `--env-file .env` before the image name in the run command.
Host-side `az login` credentials are not automatically available in the container.
Provide credentials through the standard `DefaultAzureCredential` environment
variables (such as `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`)
or a supported managed identity; never bake credentials into the image.

### GitHub Container Registry

The [container workflow](.github/workflows/container.yml) builds and smoke-tests
the frontend and API for pull requests to `main`. Pushes to `main`, `v*` tags, and
manual runs also publish to **`ghcr.io/rutzsco/enterprise-skills`** using the built-in
`GITHUB_TOKEN` with `packages: write`; no registry password secret is needed.
Main builds publish `latest` and `main`, tag builds preserve the tag (for example
`v1.0.0`), and each build receives a `sha-<short-commit>` tag.
The image's source label links the package to this repository.

After the workflow has published an image, replace `enterprise-skills:local` in
the run command above with `ghcr.io/rutzsco/enterprise-skills:latest`.
Packages may initially be private. For unauthenticated pulls, change the package
visibility to public in its GitHub package settings. Otherwise authenticate with
`docker login ghcr.io` using a token with `read:packages` and access to the package.
Publishing the package does not deploy the application.

The [private Azure deployment](infra/README.md) connects the real image to an existing Foundry project and private Blob/Cosmos endpoints through managed identity. Publishing an image does not deploy it or add user authentication. Never expose this app through public ingress.

## Connect real Foundry agents

Use an **existing Microsoft Foundry project** with a deployed model that supports function calling. The application does not provision infrastructure; the separate private deployment template provisions networking, storage, and ACA, not the model.

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

Without Foundry, you can still create/edit manual drafts, review/publish them, propose retirement/rollback, save SME notes, and use REST/MCP. You cannot generate genuine chat answers or agent proposals until Foundry is configured.

## MCP and portable packages

The pinned MCP Python SDK uses its supported 1.x maintenance API. This is a real MCP server, not a JSON-RPC-shaped REST endpoint. The app owns the session-manager lifespan and uses stateless Streamable HTTP.

| Resource | Purpose |
| --- | --- |
| `skill://index.json` | Metadata-only published index, including current release/digest and content URIs. Refresh before choosing current guidance. |
| `skill://{id}/SKILL.md` | Active approved package instructions with valid Agent Skills YAML frontmatter. |
| `skill://{id}/references/{filename}` | Optional approved text references, loaded on demand. |
| `skill://{id}/versions/{version}/SKILL.md` | Explicit historical release for review/comparison; never an implicit current-version fallback. |

MCP exposes no authoring tools, draft resources, source-note resources, or arbitrary storage paths. Retired skills are unavailable through MCP, including pinned reads. Only flat `.md`, `.txt`, or `.json` files under `references/` are allowed; executable scripts are disabled. Package IDs remain stable, lowercase, and hyphenated. Display names can contain spaces. Packages are bounded to ten references and 256 KB total.

Download a portable ZIP from `GET /api/skills/{id}/package`. It contains `{id}/SKILL.md` and any approved references, so the parent directory matches the frontmatter name. This format follows the [Agent Skills specification](https://agentskills.io/specification); the MCP URI convention is this app's explicit resource contract, not a claim that every framework automatically recognizes these resources.

### Separate consumer and impact evidence

Start the app, publish a reviewed revision to the synthetic software-purchasing skill, then run a **separate process**:

```powershell
.\.venv\Scripts\python.exe -m server.consumer `
  --endpoint http://127.0.0.1:8000/mcp `
  --question "Who needs to approve a $1,000 annual software purchase?" `
  --skill-id software-purchasing --before-version 1 `
  --output data\comparisons\purchasing.json
```

For private Azure, run this from a permitted network location and use the private app's HTTPS `/mcp` URL. The consumer uses an explicit MCP-resource-to-function adapter with Agent Framework/registered Foundry agents; it does not read the app's skill database. Its local SQLite database caches agent bindings only.

The baseline loads the explicitly pinned old release; the comparison run uses fresh discovery and the active release. Conversations are isolated, the question stays identical, and no active pointer is changed for the comparison. The report records real answers, MCP reads, exact loaded releases, model/agent version, and conversation IDs. It fails if the requested skill was not loaded or the active release has not changed. Optional `--expect-before` and `--expect-after` assert decision phrases, not exact answer wording. Review semantic correctness separately.

Every successful run creates a JSON evidence file (`data\comparisons\{id}.json` by default); an existing output file is never overwritten. There are no fabricated answers or claims of behavior improvement without actual runs.

## Publication and storage rules

Default database: `data\enterprise-memory.sqlite3`. Override its path with `MEMORY_DB_PATH` if needed. The database, WAL files, local environment, and dependency folders are ignored by Git.

- Synthetic playbooks are seeded **once per database**, not whenever the library is empty. Deleting all skills does not bring them back on restart.
- Skill IDs are stable; each new published release gets a never-reused integer version. Ordinary writes create review drafts. Approval, rollback, and retirement use optimistic concurrency.
- SME notes and review drafts persist across restarts. An interrupted organization is marked failed on startup, with the original notes retained for retry.
- Agent proposals have a separate `revision` and do not enter the published skill table until explicit approval.
- Local approval is transactional. In Azure, Blob upload/verification occurs first; a single-partition Cosmos transaction commits release metadata, the active pointer, proposal outcome, and audit event together. Blob and Cosmos do not share a transaction. Failed commits can leave invisible unreferenced package objects; never delete package prefixes automatically without checking committed references.
- An update records the exact skill ID and base version loaded by the authoring agent. Intervening manual edits or deletion make it stale; approval returns `409` rather than overwriting them. Reject and organize fresh notes against the current catalog.
- Duplicate published names are rejected case-insensitively. The authoring agent also searches for related skills to avoid semantic duplicates, but human review is still required.
- Source excerpts and per-rule quotes must be verbatim portions of the supplied notes. Each published rule receives a release-scoped ID and source intake link. This does not prove every generated statement is grounded; verify every rule before approving. Reviewer-written replacement guidance clears agent rule mappings rather than falsely retaining their attestation.
- Retirement hides the skill without deleting releases or evidence. Rollback is itself a reviewed proposal that repoints to an approved release. Its history and generation change even when it restores a previously used version.
- A first migration preserves existing current SQLite snapshots as `legacy-import` releases, without inventing overwritten history or approvals. Existing tables are retained; back up the database before migration. Synthetic bootstrap releases are explicitly marked separately and support demo rollback.
- These changes do not rewrite earlier chat messages. Subsequent active loads read fresh state, with `Cache-Control: no-store`.
- Owner and applicability are explicit fields. Missing owners remain `Unassigned`; reviewer labels are **unverified**, because the MVP has no end-user sign-in. Append-only application events are not a tamper-proof compliance audit service.

Back up the database while the server is stopped, or use SQLite's backup facilities. Do not delete the database unless you intend to reset all local skills, notes, proposals, and cached agent bindings.

## Runtime HTTP contract

Base URL: `http://127.0.0.1:8000`. These endpoints do not depend on Azure.

| Method and route | Behavior |
| --- | --- |
| `GET /api/runtime` | Describes the discovery/load contract and the local-only boundary. |
| `GET /api/runtime/skills?query=software&limit=100` | Metadata-only discovery. Searches name, description, and category using case-insensitive keyword matching. Empty query browses the catalog. |
| `GET /api/runtime/skills/{id}` | Returns the current published skill including `guidance`, identity, and version; `404` if deleted or unknown. |

Discovery returns `{ "skills": [...], "total": N, "limit": 100 }`. Entries contain identity, name, description, category, version, timestamps, owner, applicability, and digest - **never `guidance` or reference bodies**. The limit is 1-100; `total` reports all matches so consumers can detect truncation and narrow the query. This deliberately small prototype is not a large-catalog search service.

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
| `POST /api/skills` | Create a review draft from `{name, description, category, guidance, owner?, applicability?, references?}`; returns `202`, not a published skill. |
| `PUT /api/skills/{id}` | Create an update draft from fields plus `expected_version`; does not publish. |
| `DELETE /api/skills/{id}?expected_version=N` | Propose retirement; returns `202`, without deleting published history. |
| `GET /api/skills/{id}/history` | Release metadata, active pointer, and application audit events. |
| `GET /api/skills/{id}/versions/{version}` | Historical snapshot, including retired skills, for trusted control-plane review. |
| `POST /api/skills/{id}/actions` | Propose `{action: "rollback" or "retire", expected_version, target_version?, reason}` for explicit approval. |
| `GET /api/proposals/{id}/diff` | Exact instruction text diff against the immutable base release. |
| `POST /api/intakes` | Save `{title, notes}` locally; no AI request. |
| `GET /api/intakes`, `GET /api/intakes/{id}` | List saved notes / read notes, trace, and proposals. |
| `POST /api/intakes/{id}/organize` | Run the Foundry authoring agent and persist review-only proposals. |
| `GET /api/proposals`, `GET /api/proposals/{id}` | Read drafts and review outcomes. |
| `PUT /api/proposals/{id}` | Edit skill fields, `missing_information`, and `expected_revision`; never publishes. |
| `POST /api/proposals/{id}/approve` | Explicitly apply the reviewed draft/action with `{expected_revision, reviewer_label?}`. Labels are not authenticated identity. |
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

## Azure storage and deliberate MVP limits

React + TypeScript + Vite frontend; FastAPI backend. SQLite is the local document/transaction backend; Cosmos DB for NoSQL is the cloud metadata backend. Blob contains create-only package envelopes with the portable file map and exact source snapshot, verified by digest; runtime does not list Blob objects to determine publication.

The Azure metadata adapter uses one workspace partition and a conditional workspace revision in each transactional batch. It pages through the workspace to apply shared registry rules; this favors correctness for a small demo, not large-catalog scale. Transactions are bounded below Cosmos limits (100 operations / approximately 2 MB). Runtime chat handles remain process-local: keep one worker and at most one ACA replica; conversations reset after restart.

No vector database, background worker, multi-tenancy, authenticated user roles, or skill ACLs are included. Keep local binding on `127.0.0.1`; Azure requires the private networking described in [infra](infra/README.md). All permitted control-plane users can review/publish, and all permitted MCP callers can discover the published catalog. These are trusted demo boundaries, not complete enterprise governance.

No end-user Entra sign-in is required. Managed identities still use Entra for service-to-service access. Blob/Cosmos have public network access and key authentication disabled in the template. Actual MCAPS compliance requires review of applicable policies, topology, egress, access, and deployment evidence; this repository does not certify it. Use synthetic data only. Chat, SME notes, discovery metadata, and selected guidance are sent to the configured Foundry project during live runs.
