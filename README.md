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

## Daily Codex research handoff

The local Codex App automation prompt is documented in
[`docs/automation/daily-research-prompt.md`](docs/automation/daily-research-prompt.md). It
instructs Codex to research the active A-share and Hong Kong configuration, save one cited
`DailyRunRequest` JSON file, validate it, and generate a local research report. The workflow is
research-only: it must label data gaps or conflicting claims and must never trade, connect to a
broker, invent citations, or promise returns.

Before using that prompt, initialize and import the intended persisted configuration. The prompt
uses `$env:STOCK_RESEARCH_HOME/config/stocks.yaml` when set, otherwise
`.stock-research/config/stocks.yaml`:

```powershell
stock-research init
stock-research import-config .\config\stocks.example.yaml
```

After the automation has written its JSON input, the same local handoff can be checked manually:

```powershell
stock-research validate-input .\.stock-research\input\daily-research-request-YYYY-MM-DD.json
stock-research generate --input .\.stock-research\input\daily-research-request-YYYY-MM-DD.json
```
