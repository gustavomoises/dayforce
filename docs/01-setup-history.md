# Setup history: what was done, step by step

Everything below was done on Windows (PowerShell) for user Gustavo Moises, in `c:\Code\dayforce`.
Date of setup: November 5, 2026. The Dayforce task itself was not known at this point.

## 1. Starting state

- No Python installed. The `python` command only opened the Microsoft Store shortcut ("Python was not found").
- `py` launcher, `pip` and Git were not available.
- `winget` 1.29.380 was available.
- The workspace folder was empty.

## 2. Choosing the Python versions

- Checked python.org: the newest release was Python 3.15.2, with 3.14.10 as the mature series (both dated Oct 25, 2026).
- The user chose **3.14** and also asked for **3.12**, because some machines are not fully updated for 3.14.
- A first attempt to install 3.12 through winget was cancelled before approval, so nothing changed.

## 3. Installing Python 3.14 and 3.12

```powershell
winget install --id Python.Python.3.14 -e --source winget --accept-package-agreements --accept-source-agreements
winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
```

- The terminal appeared stuck (only a spinner, then a `[Y] Yes [N] No:` prompt). The prompt was the winget source agreement. Sending `N` released the terminal.
- Despite that, both versions were found on disk afterwards:
  - `C:\Users\gusta\AppData\Local\Programs\Python\Python314\python.exe` (3.14.10)
  - `C:\Users\gusta\AppData\Local\Programs\Python\Python312\python.exe` (3.12.10)
  - `C:\Users\gusta\AppData\Local\Programs\Python\Launcher` (the `py` launcher)
- The `py` command was never confirmed to work in the agent's terminal (PATH was not refreshed there). All automation used full paths instead.

## 4. Creating the virtual environments

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv312
& .\.venv312\Scripts\python.exe -m pip install --upgrade pip
```

| Folder | Python | pip |
|--------|--------|-----|
| `.venv` | 3.14.10 | 26.3 |
| `.venv312` | 3.12.10 | 26.3 |

`pip list --outdated` returned nothing for both.

## 5. Installing Git

```powershell
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
```

- Installed Git 2.56.0.4 at `C:\Program Files\Git\cmd\git.exe`. The installer asks for administrator approval (UAC).
- Verified with `git.exe --version` -> `git version 2.56.0.windows.4`.
- Set the global identity at the user's request:

```powershell
git config --global user.name "Gustavo Moises"
git config --global user.email "gustavomoises@yahoo.com"
```

## 6. Initializing the repository

- Ran `git init` in `c:\Code\dayforce`. **No commits have been made.**
- Created `.gitignore` ignoring: `.venv/`, `.venv312/`, `__pycache__/`, `*.pyc`, `.env`, `.pytest_cache/`, `.ipynb_checkpoints/`, `*.egg-info/`, `build/`, `dist/`.

## 7. Installing libraries (both environments)

```powershell
pip install --upgrade requests python-dotenv pandas openpyxl pytest
```

Resulting versions (identical in `.venv` and `.venv312`, `pip check` clean):

| Package | Version |
|---------|---------|
| requests | 2.34.2 |
| python-dotenv | 1.2.4 |
| pandas | 3.1.1 |
| numpy | 2.5.4 (pulled in by pandas) |
| openpyxl | 3.1.5 |
| pytest | 9.2.0 |

Not installed on purpose: Jupyter, pyodbc, sqlalchemy, pydantic, httpx. Add them only when the task needs them.

## 8. Project structure

Created a standard `src/` layout:

```
src/dayforce_task/__init__.py   version string
src/dayforce_task/config.py     loads .env, exposes get_setting(name, default) and DATA_DIR
src/dayforce_task/main.py       entry point, prints version and data folder
tests/.gitkeep                  empty tests folder (no tests written yet)
data/README.md                  input/output files go here
docs/                           this documentation
.env                            blank placeholders for secrets (git-ignored)
.env.example                    same keys, safe to commit
pyproject.toml                  metadata, dependencies, pytest config (pythonpath = src)
requirements.txt                pip freeze from the 3.14 environment
README.md                       project overview
SETUP.md                        environment how-to
```

`.env` keys: `DAYFORCE_BASE_URL`, `DAYFORCE_CLIENT`, `DAYFORCE_USERNAME`, `DAYFORCE_PASSWORD`, `DAYFORCE_TOKEN`. They are placeholders. The real names and values depend on the task.

Installed the project in editable mode in both environments:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv312\Scripts\python.exe -m pip install -e ".[dev]"
```

## 9. Verification performed

- `python -m dayforce_task.main` printed `dayforce_task 0.1.0` and the data folder path in both environments.
- `pip check`: "No broken requirements found" in both.
- `git check-ignore .env` -> ignored. `git check-ignore .env.example` -> not ignored (correct).

## 10. Dayforce background gathered

See [03-dayforce-notes.md](03-dayforce-notes.md).

## 11. Not done yet

- No Git commit.
- No tests written.
- Editor interpreter not selected (user must pick `.venv\Scripts\python.exe` in Kiro: "Python: Select Interpreter").
- No Dayforce credentials or API access (must come from the user/employer).
- The actual task has not been received.
