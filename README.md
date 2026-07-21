# Stock Research

Stock Research is a Python 3.12+ project for research workflows. It does not
include trading or broker integration.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the package and development tools in editable mode:

```powershell
python -m pip install -e '.[dev]'
```

Run the test suite:

```powershell
python -m pytest
```

Run linting:

```powershell
python -m ruff check .
```
