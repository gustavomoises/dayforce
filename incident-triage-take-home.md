# Take-Home Exercise: Search + AI Assistant for Incident Triage

## Timebox

1 to 3 hours (stop when you hit the timebox). Partial completion is fine if you document tradeoffs and known gaps.

## Tech choices

* Language: Python (FastAPI) or C# (ASP.NET Core)
* Search backend: anything that supports text search + basic filters (SQLite, Postgres, OpenSearch/Elasticsearch, etc.)
* LLM: must call a real LLM at runtime (OpenAI, Azure OpenAI, etc.)

We are evaluating maintainable software design and how you use AI tools, not your ability to set up complex infrastructure.

---

## What to build

### Data

Use 200 to 500 incident tickets. You can:

* Generate synthetic data (recommended), or
* Include a small sample dataset

Each incident must include:

* `id`, `created_at`, `environment` (dev/qa/stage/prod), `service`, `severity`
* `title`, `description`, `resolution_summary`, `tags` (array)

If you generate data, include the generator and a fixed seed so results are repeatable.

---

## API requirements

### 1) Ingest

`POST /ingest`

* Loads incidents into your search store
* Idempotent: running twice does not create duplicates
* Returns counts: ingested, skipped, updated (or similar)

### 2) Search

`GET /search`

Query params:

* `q` (text query)
* optional filters: `environment`, `service`, `severity`, `tags`

Returns:

* Top N results (id, title, short snippet, optional score)
* Total hit count

### 3) Incident details

`GET /incidents/{id}`

* Returns the full incident record

### 4) Assist

`POST /assist`

Input:

* `question` (string)
* optional filters (same as search)

Behavior:

1. Retrieves candidates using the same search code path as `/search` and logs it as a tool step (example: `tool:search`).
2. Calls a real LLM.
3. Returns:

    * The 3 to 5 most relevant incident IDs and why they are relevant
    * "Next steps" checklist
    * A short customer facing draft response

#### Grounding and safety rules (hard requirement)

* Must cite the incident IDs used.
* Must not invent incident details that are not in retrieved records.
* If nothing relevant is found, say so and ask for more info.
* If the LLM call fails (missing key, timeout, etc.), return a clear error explaining what to set and how to run it.

---

## Observability requirements (keep it simple)

* Generate or accept a `correlation_id` per request (header or generated).
* Include `correlation_id` in every log line.
* For `/assist`, log a step list that includes at least:

    * `tool:search` input summary (query, filters)
    * `tool:search` output summary (hit count, top IDs)
    * selected incident IDs

Optional: `GET /debug/trace/{correlation_id}` that returns recorded steps.

---

## Minimum quality requirements

### Maintainability

* Clear separation of concerns (ingest, search, assist, config, observability)
* Configuration via environment variables
* Code should be easy to extend (clean interfaces, not one giant file)

### Robustness

* Input validation and useful error messages
* Timeouts for external calls (LLM and any network calls)
* Reasonable limits (top N cap, max input size, etc.)

### Testing (minimum)

* At least 2 unit tests focused on:

    * Query building and filtering, and/or
    * Guardrails (no invented details, must cite IDs)

Integration tests are optional.

### Docs

* `README.md` with exact run steps and curl examples:

    * how to start
    * how to ingest
    * how to search
    * how to call assist
    * how to run tests

---

## Required AI documentation

### 1) PROMPTS.md (required, copy/paste prompts)

Include 5 to 10 prompts you used with AI tools. Use this template per prompt:

**Prompt #N**

* Tool used: (Cursor, Copilot Chat, ChatGPT, etc.)
* Goal: (what you wanted)
* Prompt (copy/paste):

    ```
    <your prompt here>
    ```
* Result summary: (what it produced)
* What you kept:
* What you changed manually (and why):
* Any follow up prompt(s) (copy/paste if important):
* Link to code/commit (optional):

### 2) AI-NOTES.md (required, reflection)

Include:

* How you used AI across the build (scaffolding, tests, refactors, docs, debugging)
* At least 2 examples where AI output was wrong or weak, and how you fixed it
* How you validated changes (tests, manual checks, etc.)
* Any prompt patterns you found effective

### 3) TRADEOFFS.md (required if incomplete, recommended always)

Include:

* What is done
* What is not done
* Known issues and risks
* What you would do next with 2 more hours
* What you would do next with 2 more days

---

## Environment variables (example)

Document what you use, but expect something like:

* `LLM_PROVIDER` (openai, azure-openai, etc.)
* `LLM_API_KEY`
* `LLM_MODEL`
* Provider specific vars (endpoint, deployment name, api version)
* `PORT`
* `DATA_PATH` (if applicable)

---

## Submission

Github repository or zip containing:

* Source code
* README.md
* PROMPTS.md
* AI-NOTES.md
* TRADEOFFS.md (if incomplete, recommended regardless)
* Tests
* Dataset or generator

---

## What we evaluate

* How well you steer AI tools to produce clean, maintainable code
* How you handle AI mistakes and edge cases
* Robustness and debuggability (correlation id, clear logs, safe failure modes)
* Clarity of documentation and repeatability
