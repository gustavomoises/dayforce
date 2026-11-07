# Python environment setup (Dayforce test)

> Future Kiro instances: read [docs/README.md](docs/README.md) first. It links the full setup history and a working guide.

Project folder: `c:\Code\dayforce`
Virtual environments (both already created):

| Folder | Python | Use when |
|--------|--------|----------|
| `.venv` | 3.14.10 | Default |
| `.venv312` | 3.12.10 | A package or machine isn't fully updated for 3.14 |

Every command below uses `.venv`. For 3.12, replace `.venv` with `.venv312`.

## Installed Python versions (Windows, installed with winget)

| Version | Path |
|---------|------|
| 3.14 | `C:\Users\gusta\AppData\Local\Programs\Python\Python314\python.exe` |
| 3.12 | `C:\Users\gusta\AppData\Local\Programs\Python\Python312\python.exe` |

The `py` launcher is also installed. Open a **new** terminal after installing so PATH is refreshed.
The plain `python` command may still point to the Microsoft Store shortcut. Use `py`, the full path above, or the venv.

## Project layout

```
src/dayforce_task/   application code (config.py loads .env; main.py is the entry point)
tests/               pytest tests
data/                input and output files
docs/                task instructions and notes
.env                 local secrets (git-ignored); template in .env.example
pyproject.toml       metadata, dependencies, pytest config
requirements.txt     pinned versions from the 3.14 environment
```

The project is installed in editable mode in both environments (`pip install -e ".[dev]"`), so edits under `src/` take effect immediately.

```powershell
.\.venv\Scripts\python.exe -m dayforce_task.main   # run
.\.venv\Scripts\python.exe -m pytest               # test
```

Put credentials in `.env` and read them with `dayforce_task.config.get_setting("NAME")`.

## Use the virtual environment

Run all commands from `c:\Code\dayforce`.

Activate (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run this once, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Without activating, call the venv directly (works in any shell, and for automation):

```powershell
.\.venv\Scripts\python.exe script.py
.\.venv\Scripts\python.exe -m pip install <package>
```

Deactivate: `deactivate`

## Install packages

```powershell
.\.venv\Scripts\python.exe -m pip install <package>
.\.venv\Scripts\python.exe -m pip freeze > requirements.txt   # save installed packages
.\.venv\Scripts\python.exe -m pip install -r requirements.txt # restore them
```

## Recreate the environment from scratch

```powershell
Remove-Item -Recurse -Force .venv
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

## Use Python 3.12

`.venv312` already exists. Activate it or call it directly:

```powershell
.\.venv312\Scripts\Activate.ps1
.\.venv312\Scripts\python.exe script.py
```

Packages are separate per environment. Install them in each one you use.
To recreate it: `Remove-Item -Recurse -Force .venv312; py -3.12 -m venv .venv312`
(if `py` is not found, use the full path to `Python312\python.exe` from the table).

## Check what is installed

```powershell
py --list
py -3.14 --version
.\.venv\Scripts\python.exe --version
```

## Git

Installed with winget: Git 2.56.0 at `C:\Program Files\Git\cmd\git.exe`. Open a **new** terminal so `git` is on PATH.

Global identity is already set (`Gustavo Moises`, `gustavomoises@yahoo.com`). Check with:

```powershell
git config --global user.name
git config --global user.email
```

This folder is already a git repo (`git init` done, no commits yet). `.gitignore` excludes `.venv/`, `.venv312/`, `__pycache__/`, `.env`, and test/notebook caches.

## Dayforce basics (for Python)

The task is not known yet, so confirm these against the task instructions. Dayforce is HR, payroll and workforce software with a REST API, so the task may use it, or may only use plain Python or SQL.

- **Documentation:** Dayforce Development Network, https://developers.dayforce.com. Registration is required to read it. Community FAQ: https://devcommunity.dayforce.com
- **Client namespace:** each Dayforce tenant has a short company ID. It appears in API URLs as `.../api/{clientName}/...`. The employer or Dayforce admin provides it.
- **Authentication:** OAuth token endpoints exist per environment, for example `https://dfid.dayforcehcm.com/connect/token` (production) and `https://dfidconfig.np.dayforcehcm.com/connect/token` (non-production). Some setups use an API username and password instead. Use whatever the task provides.
- **Credentials:** never put them in code. Store them in a `.env` file (already in the `.gitignore` above) or in environment variables.

Already installed in **both** `.venv` and `.venv312` (identical versions, `pip check` clean):

| Package | Version | Use |
|---------|---------|-----|
| `requests` | 2.34.2 | call REST APIs |
| `python-dotenv` | 1.2.4 | load credentials from `.env` |
| `pandas` | 3.1.1 | process tabular data |
| `numpy` | 2.5.4 | installed with pandas |
| `openpyxl` | 3.1.5 | read/write Excel files |
| `pytest` | 9.2.0 | run tests |

Not installed (add when the task needs it): `jupyter`, `pyodbc` (SQL Server), `sqlalchemy`, `pydantic`, `httpx`.

Minimal API call pattern (URL parts come from the task):

```python
import os
import requests
from dotenv import load_dotenv

load_dotenv()
resp = requests.get(
    f"{os.environ['DAYFORCE_BASE_URL']}/api/{os.environ['DAYFORCE_CLIENT']}/...",
    headers={"Authorization": f"Bearer {os.environ['DAYFORCE_TOKEN']}"},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
```

## Notes for future sessions (including AI assistants)

- Always run Python through `.\.venv\Scripts\python.exe` so the right interpreter and packages are used.
- Do not run `winget install` through an automated shell without `--accept-package-agreements --accept-source-agreements`. It can hang on a Y/N prompt.
- In VS Code / Kiro, select the interpreter `.venv\Scripts\python.exe` (Command Palette: "Python: Select Interpreter").
- Add `.venv/` to `.gitignore` if this folder becomes a git repository.
- The terminal tool may return garbled or empty output. Write results to a file (for example in `$env:TEMP`) and read that file to verify.
- Use Git by full path if it is not on PATH: `& "C:\Program Files\Git\cmd\git.exe"`.
