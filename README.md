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

## Command line

The command-line interface is limited to research reports and local configuration;
it has no trading, broker, order, or credential commands. By default its local
data is stored in `.stock-research` below the current directory. Set
`STOCK_RESEARCH_HOME` to use an explicit alternative location.

```powershell
stock-research init
stock-research import-config .\.stock-research\config\stocks.yaml
stock-research validate-input .\tests\fixtures\daily_research_request.json
stock-research generate --input .\tests\fixtures\daily_research_request.json
stock-research reports
stock-research serve --port 8000
```
