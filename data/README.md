# data

`service_catalog.json` is the incident catalog: `{service: [events]}`, 20 services × 20 events. It was generated once by `python -m app.cli catalog` (Langfuse prompt `incident-catalog`) and committed, because LLM output is not repeatable. `python -m app.cli seed` turns each event into `SEED_REPEATS` incidents with `random.Random(SEED)`, so the same file always gives the same 800 incidents.
