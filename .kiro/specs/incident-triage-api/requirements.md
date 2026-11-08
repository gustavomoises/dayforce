# Requirements Document

## Introduction

The Incident Triage API is a FastAPI service that loads synthetic incident tickets into PostgreSQL, searches them with hybrid full-text and vector search, and uses an OpenAI model to suggest the most relevant past incidents, next steps and a customer reply for a support question. It implements the take-home exercise in `incident-triage-take-home.md`.

It runs only on an existing AWS EC2 instance (us-east-2) with RDS PostgreSQL (pgvector), AWS Secrets Manager and Langfuse Cloud US. Langfuse owns prompts, tracing and log events. Design details are in `architecture.md`, `database-architecture.md`, `trace-architecture.md` and `prompts/`. Deviations from the take-home are listed in Requirement 17.

## Glossary

- **Triage_API**: the FastAPI application described in this document.
- **CLI**: the commands `python -m app.cli schema | catalog | seed | schemas`, run over SSH on EC2. Not exposed as endpoints.
- **Container**: `app/container.py`, which builds all support clients and services once and is used by the API and the CLI.
- **Schema_Service**: creates tables and indexes (DDL only).
- **Catalog_Service**: generates synthetic incident events per service with the LLM.
- **Catalog**: the committed file `data/service_catalog.json`, shaped `{service: [events]}`.
- **Seed_Service**: resets and repopulates the incident tables from the Catalog with a fixed seed.
- **Ingest_Service**: the single write path for incidents.
- **Search_Service**: hybrid search used by `/search` and `/assist`.
- **Assist_Service**: selects relevant incidents with the LLM and drafts next steps and a customer reply.
- **Type_Tables**: `environment_types`, `severity_types`, `service_types`.
- **Incident_Tables**: `incidents`, `tags`, `incident_tags` and the Type_Tables.
- **Content_Hash**: SHA-256 of an incident's canonical JSON, used to detect duplicates.
- **Pending_Embedding**: an incident whose `embedding` is `NULL` or was made with a different model than `EMBEDDING_MODEL`.
- **Candidate**: an incident retrieved by Search_Service and sent to the LLM in `/assist`.
- **APP_ENV**: per-request Langfuse label and trace environment, derived from the request's `environment` filter.
- **Correlation_ID**: per-request identifier from `X-Correlation-ID` or generated.
- **Langfuse**: Langfuse Cloud US (`https://us.cloud.langfuse.com`), the owner of prompts and traces.

## Requirements

### Requirement 1: Deployment and runtime

**User Story:** As the owner, I want the API to run on my existing EC2 instance with a public endpoint, so that reviewers can call it without setting anything up.

#### Acceptance Criteria

1. THE Triage_API SHALL run on the existing EC2 instance (us-east-2, Amazon Linux 2023, Python 3.12) using the IAM instance profile `incident-triage-ec2-role`, without recreating any AWS resource.
2. THE Triage_API SHALL start with `pip install -r requirements.txt` followed by `uvicorn main:app --host 0.0.0.0 --port 8000`.
3. THE Triage_API SHALL keep no request state in application memory, so that any number of uvicorn workers returns the same results.
4. THE Triage_API SHALL expose all endpoints publicly without authentication during the review period.
5. THE Triage_API SHALL provide schema creation, catalog generation, seeding and schema printing only as CLI commands, not as endpoints.

### Requirement 2: Configuration and secrets

**User Story:** As the owner, I want secrets read only from AWS Secrets Manager, so that no credentials are stored in code or on disk.

#### Acceptance Criteria

1. WHEN the Triage_API starts, THE Triage_API SHALL read `incident-triage/db-credentials` (keys `host`, `port`, `dbname`, `username`, `password`), `incident-triage/openai-api-key` (`OPENAI_API_KEY`), `incident-triage/langfuse-public-key` (`LANGFUSE_PUBLIC_KEY`) and `incident-triage/langfuse-secret-key` (`LANGFUSE_SECRET_KEY`) from AWS Secrets Manager in us-east-2.
2. IF a secret or a required key is missing, THEN THE Triage_API SHALL stop startup with a message naming the secret and the key, without showing any secret value.
3. THE Triage_API SHALL read non-secret settings from environment variables with defaults: `AWS_REGION` (`us-east-2`), `LANGFUSE_HOST` (`https://us.cloud.langfuse.com`), `EMBEDDING_MODEL` (`text-embedding-3-small`), `EMBEDDING_DIMENSIONS` (1536), `VECTOR_MIN_SIMILARITY` (0.30), `ASSIST_MAX_RESULTS` (5), `SEED` (42), and timeouts (LLM 30 s, embeddings 10 s, database statement 5 s).
4. THE Triage_API SHALL take the OpenAI chat model and its settings from the Langfuse prompt config, not from environment variables.
5. THE Triage_API SHALL connect to PostgreSQL with `sslmode=require`.

### Requirement 3: Layered architecture and dependency injection

**User Story:** As a reviewer, I want clear separation of concerns, so that the code is easy to read, test and extend.

#### Acceptance Criteria

1. THE Triage_API SHALL organize code in entry (routes, CLI), service, support and core layers, where imports only point to lower layers.
2. THE Triage_API SHALL place each model in the lowest layer that uses it, with shared models (`Incident`, `SearchFilters`, `LLMConfig`, `CompiledPrompt`, `LLMResult`, `EmbeddingResult`) in core and service-only models in that service's `models/` folder.
3. THE Triage_API SHALL let services use support code only through Protocols defined in `core/ports.py`.
4. THE Container SHALL build all support clients and services once at startup, and THE CLI SHALL use the same Container.
5. THE Triage_API SHALL inject services into routes with FastAPI `Depends` getters from `app/api/deps.py`, and routes SHALL contain no business logic.

### Requirement 4: Database schema

**User Story:** As the owner, I want a normalized schema with enforced value sets, so that invalid data cannot be stored.

#### Acceptance Criteria

1. THE Schema_Service SHALL create the tables `incidents`, `tags`, `incident_tags`, `service_types`, `severity_types`, `environment_types` and `query_embeddings`, with their indexes, in PostgreSQL with pgvector.
2. WHEN `cli schema` is run more than once, THE Schema_Service SHALL leave existing tables and data unchanged.
3. THE Schema_Service SHALL never insert or drop data.
4. THE Triage_API SHALL accept incident IDs only in the format `inc-` followed by 5 digits, enforced by input validation and a database `CHECK` constraint.
5. THE Triage_API SHALL use parameterized queries for every database statement.

### Requirement 5: Catalog generation

**User Story:** As the owner, I want the LLM to generate realistic events per service once, so that the seed data is realistic and the generator is repeatable.

#### Acceptance Criteria

1. WHEN `cli catalog` is run, THE Catalog_Service SHALL call the LLM once per service with the Langfuse prompt `incident-catalog` and save the result as `{service: [events]}` to the Catalog.
2. WHERE no services or event count are given, THE Catalog_Service SHALL use the 25 default services and 20 events per service.
3. IF more than 50 services, fewer than 1 service, or an event count outside 1-50 is given, THEN THE Catalog_Service SHALL reject the input with a clear message.
4. WHEN an LLM answer does not contain exactly the requested number of events, THE Catalog_Service SHALL reject that answer.
5. WHEN `GET /catalog` is called, THE Triage_API SHALL return the Catalog file without calling the LLM.
6. IF the Catalog file does not exist, THEN THE Triage_API SHALL return an error that names `cli catalog`.

### Requirement 6: Seed

**User Story:** As the owner, I want one command that rebuilds the database with identical data every time, so that results are reproducible.

#### Acceptance Criteria

1. WHEN `cli seed` is run, THE Seed_Service SHALL, without asking for confirmation, drop exactly the six Incident_Tables, call the Schema_Service, fill the Type_Tables from fixed lists, generate incidents from the Catalog and pass them to the Ingest_Service.
2. THE Seed_Service SHALL never drop `query_embeddings`, the `vector` extension, the schema or any other table.
3. THE Seed_Service SHALL generate incidents with a private `random.Random(SEED)`, services in alphabetical order, IDs in that order, `created_at` uniform between 2026-01-01 and 2026-10-31 UTC, environment weights dev 15 / qa 15 / stage 20 / prod 50 and severity weights critical 10 / high 25 / medium 40 / low 25.
3a. THE Seed_Service SHALL turn each catalog event into `SEED_REPEATS` incidents (default 1), each with a different (environment, severity) pair and its own `created_at`, so no copy is a content-hash duplicate.
4. WHEN `cli seed` is run twice with the same Catalog and `SEED`, THE Seed_Service SHALL produce identical incidents.
5. IF catalog events × `SEED_REPEATS` is below 200 or above 999, or `SEED_REPEATS` is outside 1-16, THEN THE Seed_Service SHALL stop with a message explaining what to change.
6. WHEN the seed has ingested and embedded the incidents, THE Seed_Service SHALL create an IVFFlat index on `incidents.embedding` with `vector_cosine_ops`, with `lists` = embedded rows / 1000, at least 1 and at most `IVFFLAT_MAX_LISTS` (10), and then run `ANALYZE incidents`.
7. THE Seed_Service SHALL build the IVFFlat index only after the rows exist, because IVFFlat learns its lists from the data present at creation.

### Requirement 7: Ingest

**User Story:** As a support engineer, I want to add or update incidents safely, so that the search store stays free of duplicates and invalid values.

#### Acceptance Criteria

1. THE Ingest_Service SHALL be the only code that writes incidents, used by the Seed_Service and by `POST /ingest`.
2. WHEN `POST /ingest` receives a JSON array of up to 500 incidents, THE Ingest_Service SHALL upsert them by `id`.
3. WHEN `POST /ingest` receives no body, `null` or `[]`, THE Ingest_Service SHALL write nothing and only run the embedding step.
4. IF the body is not an array, has more than 500 items, or an item has a missing field, wrong type, invalid `id`, invalid `created_at` or text over the length limits, THEN THE Triage_API SHALL reject the whole request with 422.
5. THE Ingest_Service SHALL lowercase and trim `id`, `service`, `environment` and `severity`, and lowercase, trim, deduplicate and sort tags alphabetically, while keeping the case of free text.
6. IF an incident's `environment`, `service` or `severity` is not in its Type_Table, THEN THE Ingest_Service SHALL skip it, count it as `invalid` and list the field and value.
7. THE Ingest_Service SHALL compute a Content_Hash over service, environment, severity, title, description, resolution summary and tags, with free text normalized, null and empty properties removed and keys sorted, excluding `id` and dates.
8. WHEN an incident is new, THE Ingest_Service SHALL count it as `ingested`; WHEN its `id` exists with the same Content_Hash, as `skipped`; WHEN its `id` exists with a different Content_Hash, as `updated`; WHEN its Content_Hash belongs to another `id`, as `duplicates` without storing it.
9. WHEN the same body is sent twice, THE Ingest_Service SHALL create no duplicate incidents and leave the stored incident content and embeddings unchanged.
9a. WHEN an `id` repeats within one batch, THE Ingest_Service SHALL apply the items in order so the last version wins, and write that `id` once.
10. THE Ingest_Service SHALL commit the written incidents before the embedding step, so that an embedding failure never removes saved incidents.
11. THE Triage_API SHALL respond with `ingested`, `updated`, `skipped`, `duplicates`, `invalid`, `embedded`, `embedding_pending`, `embedding_error` and `rejected`.

### Requirement 8: Embeddings

**User Story:** As a support engineer, I want incidents embedded reliably, so that search finds incidents by meaning even after an OpenAI failure.

#### Acceptance Criteria

1. THE Triage_API SHALL embed incidents with `text-embedding-3-small` (1536 dimensions) using labeled plain text of title, description and resolution, leaving out empty fields.
2. WHEN an incident's embedded text changes, or `EMBEDDING_MODEL` changes, THE Ingest_Service SHALL mark it as a Pending_Embedding; a change only to severity or tags SHALL keep the embedding.
3. WHEN any ingest call finishes its write step, THE Ingest_Service SHALL embed all Pending_Embeddings in batches of up to 100, selecting rows with `FOR UPDATE SKIP LOCKED`.
4. THE Ingest_Service SHALL never send an incident with a current embedding to OpenAI again.
5. IF OpenAI fails during the embedding step, THEN THE Ingest_Service SHALL keep the incidents, return 200 and report the pending count and the error.
6. IF an embedding response has the wrong number of vectors or wrong dimension, THEN THE Triage_API SHALL treat it as an error.

### Requirement 9: Prompts and LLM calls

**User Story:** As the owner, I want prompts and model settings managed in Langfuse, so that I can change them per environment without code changes.

#### Acceptance Criteria

1. THE Triage_API SHALL use one Langfuse text prompt per LLM call: `incident-validation` for the validation step, `incident-assist` for Assist_Service and `incident-catalog` for Catalog_Service.
2. THE Triage_API SHALL take `model`, `reasoning`, `max_output_tokens` and `text.format` (strict JSON schema) from the prompt config.
3. THE Triage_API SHALL fetch prompts with label = APP_ENV, type text and no cache.
4. THE Triage_API SHALL set APP_ENV to the request's `environment` filter for `dev`, `qa` and `stage`, to `production` for `prod`, and to `production` when no filter is given; THE CLI SHALL use `production`.
5. IF Langfuse is unreachable, the label is missing, the prompt is not a text prompt, or the config is invalid, THEN THE Triage_API SHALL return 503 explaining what to fix, without a fallback prompt.
6. THE Triage_API SHALL call the OpenAI Responses API with the compiled prompt text and the config settings.
7. IF the OpenAI key is missing or rejected, THEN THE Triage_API SHALL return 503; IF the call times out, THEN 504; IF the output does not match the output model, THEN 502 with the field errors.
8. THE Triage_API SHALL parse every LLM output into its Pydantic output model (`ValidationAnswer`, `AssistAnswer`, `CatalogBatch`), and IF the config schema name does not match the model, THEN return 503.
9. THE Triage_API SHALL insert retrieved records into the prompt as JSON between `<incidents>` markers and instruct the model to treat them as data.

### Requirement 10: Search

**User Story:** As a support engineer, I want to search incidents by text and filters, so that I can find similar past incidents.

#### Acceptance Criteria

1. WHEN `GET /search` is called with `q` and optional `environment`, `service`, `severity`, `tags` and `limit`, THE Search_Service SHALL return `total` and `results` with `id`, `title`, `snippet` and `score`.
2. THE Search_Service SHALL combine full-text search and vector search with the same filters, merged by reciprocal rank fusion, keeping vector matches only above `VECTOR_MIN_SIMILARITY`.
3. THE Search_Service SHALL require all given tags to match and SHALL cap `limit`.
4. THE Search_Service SHALL report `total` as the real number of matching incidents, without a cap.
5. WHEN `q` is empty, THE Search_Service SHALL apply only the filters and order by `created_at` descending, then `id`.
6. WHEN the same request is repeated on the same data, THE Search_Service SHALL return the same `total`, IDs and order, by ending every sort with `id`, rounding similarity to 6 decimals and reusing stored query embeddings.
7. IF a filter value is invalid, THEN THE Triage_API SHALL return 422.
8. IF the query embedding call fails, THEN THE Triage_API SHALL return 503 without falling back to text-only search.
9. WHEN a search runs the vector branch, THE Search_Service SHALL order by cosine distance (`<=>`) with a `LIMIT` so the IVFFlat index can be used, and SHALL set `ivfflat.probes` to `IVFFLAT_PROBES` (10) for that transaction; because probes ≥ lists, results are exact and reproducible.

### Requirement 11: Incident details

**User Story:** As a support engineer, I want to open a full incident record, so that I can read its complete description and resolution.

#### Acceptance Criteria

1. WHEN `GET /incidents/{id}` is called with an existing ID, THE Triage_API SHALL return the full record with tags in alphabetical order.
2. IF the ID does not exist, THEN THE Triage_API SHALL return 404.

### Requirement 12: Assist

**User Story:** As a support engineer, I want grounded suggestions for a question, so that I can resolve it faster without invented details.

#### Acceptance Criteria

1. WHEN `POST /assist` is called with a `question`, optional filters and optional `candidate_multiplier` n, THE Assist_Service SHALL collect up to n × `ASSIST_MAX_RESULTS` valid Candidates (default n = 3, so 15) through the Search_Service and the validation step.
1a. THE Assist_Service SHALL validate search hits with the Langfuse prompt `incident-validation` before fetching full records: each hit is `valid` true/false with a reason, where valid means it has the same failure type as the question (and the same product area or service when the question names one); a shared product area or generic word alone is not enough, and the verdict must agree with its reason.
1b. THE validation step SHALL send at most `VALIDATION_BATCH_SIZE` (15) hits per LLM call, most similar first; each next batch SHALL start after the hits already checked and be sized by the valid rate seen so far; it SHALL stop when enough hits are valid, search has no more hits, a whole batch is invalid, or `VALIDATION_MAX_BATCHES` (4) calls were made.
1c. THE Assist_Service SHALL pass only valid Candidates to `incident-assist`, which then only judges relevance and ranks; the response SHALL include every validation verdict.
1d. THE `incident-assist` call SHALL give every relevant Candidate a rank (1..k across all relevant) and a group (same problem, any wording), groups numbered in the order their best-ranked Candidate appears, and a `group_reason`; a group SHALL share the same root cause and fix (a shared symptom alone is not enough). THE Assist_Service SHALL return one entry per group (at most `assist_max_results` groups) led by its best-ranked incident, with the other members as `related` (rank, id, title, reason, group_reason, environment, severity, created_at), without another database query; the note counts distinct problems (groups).
2. IF n is outside 1-5 or the question is empty or too long, THEN THE Triage_API SHALL return 422.
3. WHEN no valid Candidates are found, THE Assist_Service SHALL return `no_relevant_incidents` with `missing_info` and the validation verdicts, without calling `incident-assist`.
4. WHEN Candidates are found, THE Assist_Service SHALL make one LLM call and require, for every Candidate, `relevant` true or false with a `reason`, and for relevant Candidates a `rank` and `rank_justification`, plus `next_steps`, `customer_draft` and `missing_info`.
5. THE Assist_Service SHALL never trust LLM output with real data: IDs not sent to the LLM (in validation or assist) SHALL be removed, next steps citing no incident or any ID that is not a kept relevant Candidate SHALL be removed, and ranks and groups SHALL be renumbered 1..k without gaps; titles, environments, severities and dates SHALL come from the database, never from the LLM.
5a. IF the output misses a Candidate, repeats one, repeats a rank, gives a rank or group to a non-relevant Candidate, omits a rank, group or justification for a relevant one, or has an empty reason, THEN THE Assist_Service SHALL reject the output with 502.
6. WHEN no Candidate is relevant, THE Assist_Service SHALL return `no_relevant_incidents` with `missing_info`.
7. WHEN at least one Candidate is relevant, THE Assist_Service SHALL return one entry per group sorted by rank, at most 5 groups, never padded, with the note "only N distinct problem(s) found" when N is 1 or 2, and SHALL also return the full grounded Candidate list.
8. THE Assist_Service SHALL use only retrieved records, cite incident IDs in next steps, and keep incident IDs and promises out of the customer draft.

### Requirement 13: Observability

**User Story:** As the owner, I want every request traced and logged in Langfuse with a correlation ID, so that I can debug any request end to end.

#### Acceptance Criteria

1. THE Triage_API SHALL take the Correlation_ID from `X-Correlation-ID` or generate one, and return it in the response header and in every error body.
2. THE Triage_API SHALL record every request and CLI command as one Langfuse trace with trace ID derived from the Correlation_ID, environment APP_ENV and the Correlation_ID in metadata.
3. THE Triage_API SHALL record the search, incident, catalog and assist steps as nested Langfuse observations through Langfuse's `@observe`, LLM calls as generations and embedding calls as embeddings; ingest, seed and schema work SHALL appear as log events and embedding observations under the root.
4. THE Triage_API SHALL keep no trace store of its own.
5. WHEN `GET /debug/trace/{correlation_id}` is called, THE Triage_API SHALL return the trace's observations as Langfuse returns them, plus the Langfuse URL; IF none exist yet, THEN 404 "retry shortly"; IF Langfuse is unreachable, THEN 503.
6. THE Triage_API SHALL flush observations to Langfuse after each response and on shutdown.
7. THE Triage_API SHALL write every log line to stdout as JSON with the Correlation_ID and observation ID, and WHILE an observation is active, SHALL also send the line to Langfuse as an event (except `DEBUG`).
8. IF sending a log event to Langfuse fails, THEN THE Triage_API SHALL keep the stdout line and continue the request.
9. WHEN `/assist` runs, THE Triage_API SHALL log `step tool:search input` (query, filters, limit, offset), `step tool:search output` (hit count, top IDs), `step validation` (checked, valid IDs, target = n × 5) and `step selected_ids`; n is on the root observation input.
10. THE Triage_API SHALL never record secrets in logs or traces, SHALL record embedding counts instead of vectors, and SHALL cut log-event metadata to 200 characters.
11. THE Triage_API SHALL not use the legacy Langfuse ingestion endpoint or deprecated SDK calls.

### Requirement 14: Robustness

**User Story:** As a reviewer, I want safe failure modes and clear errors, so that problems are easy to diagnose.

#### Acceptance Criteria

1. THE Triage_API SHALL validate every input with Pydantic and return 422 with useful field messages.
2. THE Triage_API SHALL apply timeouts to every external call.
3. THE Triage_API SHALL enforce limits: 500 incidents per ingest, title 200 characters, description and resolution 5000 characters, 20 tags of 50 characters, a search `limit` cap, a question length limit and `max_output_tokens` from the prompt config.
4. THE Triage_API SHALL return errors as `{error, detail, correlation_id}` and never a stack trace.
5. WHEN `GET /health` is called, THE Triage_API SHALL report app status and database reachability.

### Requirement 15: Tests

**User Story:** As a reviewer, I want automated tests, so that I can trust the behavior.

#### Acceptance Criteria

1. THE Triage_API SHALL have unit tests for every component listed in the architecture documents, using fakes through Protocols and `dependency_overrides`, with no AWS access.
2. THE unit tests SHALL include query building and filtering, and guardrails.
3. THE Triage_API SHALL have live tests marked `live` that call the running EC2 API, skipped unless `API_BASE_URL` is set, covering ingest twice, search, details, assist, catalog and debug trace.
4. WHEN `pytest` is run without options, THE test suite SHALL run only unit tests.

### Requirement 16: Deliverables

**User Story:** As a reviewer, I want complete documentation, so that I can run, test and evaluate the work.

#### Acceptance Criteria

1. THE repository SHALL include `README.md` with run steps and curl examples for start, ingest, search, assist and tests; EC2 deployment steps SHALL be confirmed with the owner before writing.
2. THE repository SHALL include `PROMPTS.md` with 5-10 prompts from `docs/prompt-log.md`, `AI-NOTES.md` with at least 2 AI mistakes and fixes, and `TRADEOFFS.md`.
3. THE repository SHALL include `postman_collection.json` using `{{base_url}}`, and THE Triage_API SHALL keep FastAPI `/docs` enabled.
4. THE repository SHALL include the generator: Catalog_Service, the committed Catalog and Seed_Service with a fixed seed.

### Requirement 17: Documented deviations from the take-home

**User Story:** As a reviewer, I want deviations stated openly, so that I can judge them as decisions, not omissions.

#### Acceptance Criteria

1. THE `TRADEOFFS.md` SHALL explain that `/assist` may return 1 or 2 incidents instead of "3 to 5" when fewer are relevant, and never pads.
2. THE `TRADEOFFS.md` SHALL explain that seeding is a CLI command and that `POST /ingest` upserts a body or retries pending embeddings.
3. THE `TRADEOFFS.md` SHALL explain that search depends on OpenAI for query embeddings and returns 503 when it is unavailable.
4. THE `TRADEOFFS.md` SHALL explain that the endpoints are public without authentication for the review period.
5. THE `TRADEOFFS.md` SHALL explain that the seed creates 500 incidents (500 catalog events × 1 repeat) and why the earlier 800-incident seed and 25 events per service were dropped.
