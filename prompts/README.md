# Langfuse prompts (version 1)

The app reads prompts from Langfuse, not from these files. These files are the source copy to paste into Langfuse and to review in git.

| Langfuse prompt | Type | Text | Config |
|-----------------|------|------|--------|
| `incident-assist` | text | `incident-assist.txt` | `incident-assist.config.json` |
| `incident-validation` | text | `incident-validation.txt` | `incident-validation.config.json` |
| `incident-catalog` | text | `incident-catalog.txt` | `incident-catalog.config.json` |

## Create in Langfuse (us.cloud.langfuse.com)

1. Prompts → New prompt. Name as above, type **Text**.
2. Paste the `.txt` file as the prompt text. Variables use `{{name}}`.
3. Paste the `.config.json` file as the config.
4. Add the labels `dev`, `qa`, `stage`, `production` (the app picks the label from the request's `environment`; `prod` → `production`, none → `production`).

## Variables

| Prompt | Variable | Filled by the app with |
|--------|----------|------------------------|
| `incident-assist` | `question` | the user's question |
| | `filters` | the filters as JSON, or `none` |
| | `incidents` | retrieved records as a JSON array (`id`, `service`, `environment`, `severity`, `created_at`, `title`, `description`, `resolution_summary`, `tags`) |
| `incident-validation` | `question` | the user's question |
| | `filters` | the filters as JSON, or `none` |
| | `incidents` | one search batch (at most 15) as a JSON array (`id`, `title`, `snippet`) |
| `incident-catalog` | `service` | service name, for example `payroll-service` |
| | `count` | events per service (default 20) |

## Model

`gpt-6.1-terra`, reasoning effort `medium` (the model default) for assist and catalog, `low` for validation (a yes/no screen per incident, so faster and cheaper). Structured outputs with strict JSON schema. No `temperature` (not set for reasoning models). `max_output_tokens` includes reasoning tokens, so it is set well above the expected answer size: 6000 for assist, 12000 for a 20-event catalog batch.

## Keeping schemas in sync

The JSON schemas here must match the Pydantic output models (`AssistAnswer`, `CatalogBatch`). `python -m app.cli schemas` regenerates them from the models, and a unit test fails if these files and the models differ.
