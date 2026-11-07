# Prompt log (source for PROMPTS.md and AI-NOTES.md)

Prompts given to AI tools while building, copied as written. Pick the best 5-10 for `PROMPTS.md` at the end. Corrections ("what changed") feed the AI-NOTES "AI was wrong" examples.

App prompts (`incident-assist`, `incident-catalog`) are versioned in Langfuse and copied to `prompts/`; they are not logged here.

---

**#1 Layered architecture**
- Tool: Kiro (chat)
- Goal: define the project architecture before writing code.
- Prompt:
  ```
  project architecture: Create a md called architectre.md; each endpoint of fastAPi is hollow that call a service, I want a service layer (business layer) and support layer (langfuse, opeai, datbase). Each model is in a older inside each service, Just add be wise to where you add the moldel, never add model in a lower service that is use in a upservce. chaeck my architecture with incident-trige-take-home. create memrmaid daigrams to ilustrate. you also need to do unit tests for each component, service,...reade the icinident traigem and check if the architectureproposes is good and whoud you suggest to improve.
  ```
- Result: `architecture.md` with layers, structure, Mermaid diagrams, test plan, take-home check.
- Kept: thin routes, service and support layers, test per component.
- Changed: first draft was too long ("I asked for a md not a PhD thesis"); AI added a `core` layer so shared models (`Incident`, `SearchFilters`) don't force a lower layer to import from a higher one.

**#2 Seed vs ingest order**
- Tool: Kiro (chat)
- Goal: clarify who populates the database.
- Prompt:
  ```
  you are worng we will poulate first with the see service and aply the ingest service it is the opposite, ignets service is aservice that will be used toa dd later
  ```
- Result: SeedService generates incidents and calls IngestService; IngestService is the single write path, reused by `POST /ingest`.
- Changed: AI had IngestService calling SeedService (backwards). Corrected by the user.

**#3 Content hash for duplicates**
- Tool: Kiro (chat)
- Goal: detect duplicate incidents.
- Prompt:
  ```
  I want you to add key .to incente for SHA256 encruption of whr incident. we will create a JSON object and clear the text of extra space and especial cahracters, so we can check if you are not addinf a similar incidente
  ```
- Follow-up:
  ```
  I would recommend to add the tags in alphabetical order, and remove any null property. In the database service we will ned to add a defenseive check: enviroment must be in types, like service and severity. if not we will need to skip and count that and the service reply
  ```
- Result: normalized canonical JSON + SHA-256 `content_hash` (unique), defensive type check with `invalid` count.
- Changed: AI pointed out SHA-256 is a hash, not encryption. User added alphabetical tags, null removal and the defensive check.

**#4 Embedding model (AI wrong, then right)**
- Tool: Kiro (chat + web search)
- Goal: choose an OpenAI embedding model.
- Prompt:
  ```
  what is the best embedding that you recommend that is active in openAI and what whould be embedded
  ```
- Follow-ups:
  ```
  you are worng on of them was deprecated and theres ada-002
  ```
  ```
  ia notcrazy Yes, OpenAI sent an email to developers stating that text-embedding-3-small would be deprecated, but they quickly reversed it and admitted it was a mistake.
  ```
- Result: `text-embedding-3-small`, labeled plain text of title, description, resolution.
- Changed: AI first omitted `ada-002` from the comparison, then dismissed the user's deprecation memory without checking the OpenAI forum. A forum search confirmed the April 2026 mistaken email and its correction. Lesson: search before contradicting the user.

**#5 Embeddings must never block saving**
- Tool: Kiro (chat)
- Goal: make ingest safe when OpenAI fails.
- Prompt:
  ```
  not null does scare me, if open ai fail i need to be able to save the incedent and later in the next call find the missing embedding and do again idenpotnent ok
  ```
- Result: nullable `embedding`, save first, embed pending rows on every ingest call (also with an empty body), `FOR UPDATE SKIP LOCKED`.
- Changed: AI's first design failed the whole ingest when OpenAI failed.

**#6 Langfuse owns tracing**
- Tool: Kiro (chat)
- Goal: stop duplicating Langfuse.
- Prompt:
  ```
  that is why I didn;t undersatnd your question Langfuse is the guardian of the tracing don;t try to do its job
  ```
- Result: removed the in-memory trace store and custom span tree; `traced` = Langfuse `@observe`; `/debug/trace` reads from Langfuse unchanged.
- Changed: AI had built a parallel trace store, which also broke with several uvicorn workers.

**#7 Environment as Langfuse label**
- Tool: Kiro (chat)
- Goal: select prompt version per environment.
- Prompts:
  ```
  use the endpoint environemt if provided it defien the APP_ENV
  ```
  ```
  the environemnts re clerly define in the take home
  ```
  ```
  but in langfuse there is no prod it is production OK?
  ```
- Result: request `environment` → Langfuse label and trace environment; `prod` → `production` only at the Langfuse boundary; none → `production`.
- Changed: AI first invented its own values, then dropped the mapping; user corrected both.

**#8 Relevance with explicit true/false**
- Tool: Kiro (chat)
- Goal: make `/assist` selection auditable.
- Prompts:
  ```
  yes. we have the input I can check after if the output, just add to schema to return provideing the relevance order, justifying it
  ```
  ```
  you must had bollen relavant tru or false
  ```
  ```
  we need to send 3 times for instance 15 most similar tickets and ask to select
  ```
- Result: every candidate judged `relevant` true/false with a reason; relevant ones ranked with `rank_justification`; `n` × 5 candidates (default 15) in one call; never padded to 3.

**#9 Inject services into endpoints**
- Tool: Kiro (chat)
- Goal: keep routes thin and testable.
- Prompt:
  ```
  can e inject the service in the endpoints ?
  ```
- Result: `app/container.py` builds clients and services once (lifespan, shared with CLI); `app/api/deps.py` getters; routes use `Depends`; tests use `dependency_overrides`.

**#10 Code quality for parallel agents**
- Tool: Kiro (chat)
- Goal: keep code quality consistent across sub-agents working in parallel.
- Prompt:
  ```
  when you write the code because of the time you will need to rly in other agents, tell teh agenst to be samert and concise and find elagant and simple solutions taht are afective, following the best practive and design pattern. make the code pristine
  ```
- Result: always-included steering file `.kiro/steering/code-standards.md` (spec as source of truth, layers, style, patterns, definition of done), repeated in each sub-agent's instructions.

**#11 Related incidents decided by the LLM**
- Tool: Kiro (chat)
- Goal: stop showing the same problem several times in `/assist`, without relying on identical text.
- Prompt:
  ```
  groups don't have to have the same title, they should be related if the llm says incidents are related; use the most relevant as first one and say these are related incidents of this relevant ticket
  ```
- Result: `incident-assist` v3 adds `related_to` per candidate. The lead of each group is ranked; the others point to it and are returned under `related` with their reason. Text-hash clustering removed; guardrails check `related_to` names a ranked candidate.

**#12 Rank plus group per relevant incident**
- Tool: Kiro (chat)
- Goal: cluster related incidents to avoid repetition, keeping one global relevance order.
- Prompt:
  ```
  let's see if you got ticket A group1 relevance 1, ticketB group 1 relevance 2, ticket C group 2 relevance 3
  ```
- Result: `incident-assist` v4 gives each relevant candidate a global `rank` and a `group` (numbered by first appearance in rank order), replacing `related_to`. The response has one entry per group led by its best-ranked incident, with the other members under `related` with their own rank; top 5 counts groups.

**#13 Grouping reason and clustering rules**
- Tool: Kiro (chat)
- Goal: groups mixed incidents with the same symptom but different causes; make each grouping explainable.
- Prompt:
  ```
  add a reason for grouping
  add clustering group rules
  ```
- Result: `incident-assist` adds `group_reason` per relevant candidate and clustering rules (same root cause AND same fix; a shared symptom is not enough; environment, severity or date differences do not split a group; when unsure, keep separate). The lead now shows environment, severity and created_at; the note counts distinct problems.

**#14 Never trust the LLM with real data**
- Tool: Kiro (chat)
- Goal: make sure every incident in the response exists in what was sent to the LLM.
- Prompt:
  ```
  after the response from LLM you check if the incident exists based on the most similar call? never trust LLM with real data always check the output based on the input. if it doesn't exist remove this from the response
  ```
- Result: unknown IDs used to reject the whole answer (502). Now `guardrails.ground` and `screening.ground_verdicts` remove IDs not sent to the LLM, drop next steps citing no incident or a non-relevant/unknown one, and renumber ranks and groups. Titles, environment, severity and dates already came from the database.

**#15 Stricter validation**
- Tool: Kiro (chat)
- Goal: validation passed every payments incident (shared product area), even when its own reason said the failure type did not match.
- Prompt:
  ```
  yes   (to the proposal: valid only for the same failure type; a shared product area or generic word is not enough; the verdict must agree with the reason)
  ```
- Result: `incident-validation` v4 text. Rule 2 requires the same failure type (plus the product area when the question names one), rule 3 rejects area-only or word-only matches, rule 5 forces the verdict to agree with the reason. Config unchanged.

**#16 Full unit suite with parallel agents**
- Tool: Kiro (chat, three sub-agents in parallel)
- Goal: finish task 7 quickly without the agents editing the same files.
- Prompt:
  ```
  finsih all the unit tests in 7 use up 3 agents in parallel please
  ```
- Result: one agent per stream (core + database, Langfuse + OpenAI, services + routes + properties), each owning its own test files; 343 tests. The agents reported bugs as strict xfail instead of fixing app code. One real bug fixed: 500 responses lost the correlation_id.

**#17 Repeated id in one ingest batch**
- Tool: Kiro (chat)
- Goal: decide what a batch that repeats an id means for idempotence.
- Prompt:
  ```
  why can't we have it on is insert other is update? or both updates?
  winner takes all. do what is best and inform the decission
  ```
- Result: last version wins. Items apply in order and the id is written once. A re-run leaves rows and embeddings unchanged (no OpenAI call) but may count the repeated items as `updated`. Rejected: refusing repeated ids (stricter, but loses a valid "last write" use). Recorded in requirement 7.9a and design Property 3.

**#18 Documentation with diagrams**
- Tool: Kiro (chat, three sub-agents in parallel)
- Goal: finish task 8 so the project can get a final review.
- Prompt:
  ```
  do full task 8 so we can do a final revision, alwaus use mermaid daigram to explain our decisions to make sure they fully understand each cahnge and archtect approach. what will be missing is the prompt fine tuniing that we should after all docs are ready
  ```
- Result: one agent for live tests and Postman, one for the architecture docs, one for PROMPTS/AI-NOTES/TRADEOFFS; README and cleanup by the main agent. Every decision has a Mermaid diagram. The doc agent found spec lines that no longer matched the code (prompt list, step log fields, truncation wording); requirements were corrected. Prompt fine-tuning added as task 9.
