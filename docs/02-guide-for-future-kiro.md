# Guide for future Kiro instances

Read this first. It tells you how this workspace is set up and what to watch out for.

## Facts

- Workspace: `c:\Code\dayforce`. OS: Windows, shell: PowerShell.
- User: Gustavo Moises. Goal: prepare for a Dayforce job test, written in Python. The task was **not received** when this was written. Check `docs/` for task instructions before assuming anything.
- Two virtual environments exist:
  - `.venv` = Python 3.14.10 (default)
  - `.venv312` = Python 3.12.10 (use if something is not compatible with 3.14)
- Both have: requests, python-dotenv, pandas, numpy, openpyxl, pytest, and the project installed in editable mode.
- Git is installed at `C:\Program Files\Git\cmd\git.exe`. Global name and email are set. The repo has no commits.
- Secrets go in `.env` (git-ignored). Never print, log, or commit them.

## How to run things

Always use the environment's interpreter by path. Do not rely on `python` or `py` being on PATH in the agent terminal.

```powershell
.\.venv\Scripts\python.exe -m dayforce_task.main
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip install <package>
```

If a library is added, install it in **both** environments, add it to `pyproject.toml` `dependencies`, and refresh `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m pip freeze --exclude-editable | Out-File requirements.txt -Encoding ascii
```

Git by full path if needed: `& "C:\Program Files\Git\cmd\git.exe" status`.

## Terminal pitfalls seen in this setup

1. **Output is unreliable.** The terminal tool often returns only the echoed command text, an empty result, or a spinner, with exit code -1. The command may still have succeeded.
   - Fix: write results to a file (for example `$env:TEMP\result.txt`) and read it with the file-read tool.
2. **Do not read the result file in the same step as the command that writes it.** The command may still be running. Run the command, then wait (poll with a loop like `while (-not (Test-Path $f)) { Start-Sleep 3 }`), then read the file in a separate step.
3. **winget can hang on a Y/N prompt.** Always pass `--accept-package-agreements --accept-source-agreements` (add `--disable-interactivity`). Installers such as Git ask for administrator approval (UAC), which the user must click.
4. **Long installs are slow.** Installing pandas into both environments took several minutes. Check progress by listing `.venv\Lib\site-packages` instead of re-running the command.
5. **New PATH entries need a new terminal.** After installing Python or Git, the user's existing windows do not see them. The agent terminal may not either, so use full paths.
6. **Never run long-running servers or watchers in the agent terminal** (for example `jupyter notebook`, `npm run dev`). Ask the user to run them.

## Conventions to keep

- Application code in `src/dayforce_task/`, tests in `tests/`, data files in `data/`, notes in `docs/`.
- Read configuration through `dayforce_task.config.get_setting("NAME")`.
- Do not commit `.env`, the virtual environments, or data containing personal or payroll information.
- Do not add features, tests or refactors the user did not ask for. Confirm scope first.
- Before saying a step worked, verify it (run it, or read back the file or version). Say plainly when something could not be verified.

## When the task arrives

1. Save the instructions in `docs/` (for example `docs/task.md`).
2. Read them for: required Python version, libraries, input files, how results are submitted.
3. Install what is missing in both environments and update `pyproject.toml` and `requirements.txt`.
4. Update `.env.example` and `.env` with the real setting names from the task.
5. Add a new section to [01-setup-history.md](01-setup-history.md) or a new numbered file describing what changed.

## Keep these docs current

When you change the environment, tools, structure or workflow, update `docs/` and `SETUP.md` in the same session.
