# Stock Research

Stock Research is a local, research-only workflow for configured mainland China A-shares and
Hong Kong stocks. It combines cited research input with completed daily market bars, produces
JSON, Markdown, and HTML reports, and serves the same saved history through a local dashboard.
It does not place trades, connect to a broker, or store broker credentials.

## Setup

Python 3.12 or newer is required. From the repository root, create a virtual environment and
install the package with its development tools:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

The `stock-research` launcher is installed into the active environment. If it is not on `PATH`,
use `.\.venv\Scripts\stock-research.exe` on Windows or `.venv/bin/stock-research` on macOS/Linux.

## First configuration

Create an editable YAML configuration, review its sample A-share, Hong Kong, industry, and
optional holding values, then import it:

```bash
stock-research init config/stocks.yaml
stock-research import-config config/stocks.yaml
```

`init` refuses to overwrite an existing file. `import-config` validates the complete YAML before
atomically replacing the active stock set. YAML is only an import input. After import, the daily
source is the SQLite-backed persisted active repository; editing YAML alone does not change the
active set. The web configuration screens update that same repository.

To inspect the exact active daily symbols, names, and markets from that repository, use the same
read-only service call as the Codex prompt:

```powershell
python -c 'from stock_research.cli import build_services; import json; print(json.dumps([dict(symbol=stock.symbol, name=stock.name, market=stock.market.value) for stock in build_services().configuration.list_stocks()], ensure_ascii=False))'
```

By default, configuration state and report history are stored locally under `.stock-research/` in
the current directory. Set `STOCK_RESEARCH_HOME` before every command and automation run to use a
different local app home. The app home contains SQLite databases and generated reports; it does
not contain broker credentials, orders, or model API credentials.

## Daily research workflow

The Codex App prompt is [docs/automation/daily-research-prompt.md](docs/automation/daily-research-prompt.md).
It tells Codex to read the SQLite-backed active A-share/Hong Kong set, research the last completed
sessions, preserve source metadata, label unverified or conflicting claims, write one
`DailyRunRequest` JSON file, validate it, generate the report, and inspect the outputs. Running
that automation requires the Codex App to be available; it does not require user-supplied model
API credentials. The automation is a research handoff, not an operating-system scheduler or a
broker integration.

For a manual run, place the cited request in the inbox and use these commands:

```bash
stock-research validate-input data/inbox/2026-07-21.json
stock-research generate --input data/inbox/2026-07-21.json
stock-research reports
stock-research serve --port 8000
```

`validate-input` checks the JSON schema without fetching prices or writing a report. `generate`
reads the persisted active stock set, retrieves completed daily bars, builds the report, and prints
the three output paths. `reports` lists saved dates and statuses. `serve` starts the local dashboard
on `http://127.0.0.1:8000`; it binds only to loopback.

The complete CLI is:

```text
stock-research init [OUTPUT_PATH]
stock-research import-config INPUT_PATH
stock-research validate-input INPUT_PATH
stock-research generate --input INPUT_PATH
stock-research reports
stock-research serve --port 8000
```

There are no buy, sell, order, broker, or credential commands.

## Outputs and interpretation

Each run is saved below `<app-home>/reports/YYYY-MM-DD/` as `report.json`, `report.md`, and
`report.html`. All formats retain the stock identity, report and generation dates, market state,
data-as-of dates, warnings, data gaps, disclaimer, analysis sections, short/medium/long horizons,
and source links. SQLite stores the active configuration, report history, and run records used by
the CLI and dashboard.

Read the dates separately: `report_date` is the intended research day, `generated_at` is when the
request was assembled, and each market/research/technical `data_as_of` value identifies the last
data actually used. A holiday, suspension, delayed source, or unavailable quote can therefore make
the data-as-of date earlier than the report date.

Run statuses mean:

- `success`: every configured stock had valid research and usable completed price history.
- `partial`: some valid output exists, but at least one configured stock, cited source, or price
  input was unavailable or incomplete.
- `failed`: an unexpected run-level error prevented a normal report from completing; inspect the
  recorded stage and error message before retrying.

The short-, medium-, and long-horizon sections are conditional research observations. Their
triggers, invalidation conditions, position limits, confidence, and risks are not orders or return
promises. Before acting on any report, read its **来源与数据缺口** (sources and data gaps) section,
open the cited sources, check the run warnings and market dates, and account for any conflicting or
unverified claims. A `partial` report must not be read as complete coverage.

## Failure recovery

- If the active set is empty, run `import-config` again with the intended YAML and confirm the same
  `STOCK_RESEARCH_HOME` is used by setup, manual commands, the dashboard, and Codex.
- If `validate-input` fails, correct the reported JSON field, timestamp, citation, or symbol
  mismatch. Do not invent evidence or bypass validation.
- If a run is `partial`, keep the valid output, then investigate every warning and per-stock data
  gap. Retry only after the missing source or completed market data is available.
- If generation fails, inspect the CLI error and the local run record, correct the input,
  configuration, filesystem, or data-access issue, and rerun the same validated request.
- If the dashboard port is occupied, choose another local port, for example
  `stock-research serve --port 8001`.

## Development validation

```powershell
python -m pytest -v
python -m ruff check .
stock-research --help
```
