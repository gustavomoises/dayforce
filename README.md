# Dayforce task

Python project for the Dayforce job test. Environment setup and tooling notes are in [SETUP.md](SETUP.md).

## Layout

```
src/dayforce_task/   application code (import as `dayforce_task`)
tests/               pytest tests
data/                input and output files
docs/                notes and task instructions
.env                 local secrets (not committed); template in .env.example
pyproject.toml       project metadata, dependencies, pytest config
requirements.txt     pinned versions of installed packages
```

## Run

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m dayforce_task.main
python -m pytest
```
