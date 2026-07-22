# Stock Research

Stock Research is a local, research-only workflow for configured mainland China A-shares, Beijing
Stock Exchange (BSE), and Hong Kong stocks. It combines cited research input with completed daily market bars, produces
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

## Feishu report notification

Every successful `stock-research generate --input ...` saves the JSON, Markdown, and HTML report
first, then sends the complete Markdown report to a locally configured Feishu V2 custom-bot
Webhook. This includes manual runs and repeat runs. The Webhook is read only from the user-level
`STOCK_RESEARCH_FEISHU_WEBHOOK_URL` environment variable and is never stored in this repository.

On Windows, configure it without placing the URL in a source or configuration file:

```powershell
[Environment]::SetEnvironmentVariable('STOCK_RESEARCH_FEISHU_WEBHOOK_URL', '<your-feishu-v2-webhook>', 'User')
```

Restart the Codex App or terminal after setting the variable so future local automation processes
inherit it. Feishu's single V2 request-body limit is 20KB; the application uses a conservative
18KiB limit and sends an overlong report as numbered UTF-8-safe text segments. If a notification
fails, the report remains saved and its original run record remains available, but `generate`
returns a nonzero status and identifies the failed notification segment. Correct the local
environment setting or webhook availability, then explicitly run `generate` again; the report is
sent again rather than silently retried.

## First configuration

Create an editable YAML configuration, review its sample A-share, BSE, Hong Kong, industry, and
optional holding values, then import it:

```bash
stock-research init config/stocks.yaml
stock-research import-config config/stocks.yaml
```

`init` refuses to overwrite an existing file. `import-config` validates the complete YAML before
atomically replacing the active stock set. YAML is only an import input. After import, the daily
source is the SQLite-backed persisted active repository; editing YAML alone does not change the
active set. The web configuration screens update that same repository.

Use `SH.######` or `SZ.######` for Shanghai/Shenzhen A-shares, `BJ.9#####` for current BSE
securities (for example, `BJ.920808`), and `HK.#####` for Hong Kong securities.

To inspect the exact active daily symbols, names, markets, industries, and optional holding-risk
context from that repository, use the same read-only service call as the Codex prompt:

```powershell
python -c 'from stock_research.cli import active_stock_context; import json; print(json.dumps(active_stock_context(), ensure_ascii=False))'
```

This lookup reads only an existing persisted configuration database. If it is absent, it reports a
configuration block and does not create an app-home directory, database, or report artifact.

By default, configuration state and report history are stored locally under `.stock-research/` in
the current directory. Set `STOCK_RESEARCH_HOME` before every command and automation run to use a
different local app home. The app home contains SQLite databases and generated reports; it does
not contain broker credentials, orders, or model API credentials.

## Daily research workflow

The Codex App prompt is [docs/automation/daily-research-prompt.md](docs/automation/daily-research-prompt.md).
The two automatic tasks use this same prompt: 09:00 China Standard Time passes `pre_market`, and
23:00 China Standard Time passes `post_market`. Automatic requests must always include one of these
explicit `run_slot` values. The post-market task may use the report date as a market's completed
session only after it confirms that market has closed; otherwise it records a Simplified Chinese
data gap and uses the last verifiable session. The prompt tells Codex to read the SQLite-backed
active A-share/BSE/Hong Kong set, preserve source titles and URLs, write Simplified Chinese research
summaries/event descriptions/data-gap explanations, validate one `DailyRunRequest` JSON file,
generate the report, and inspect the outputs. Running that automation requires the Codex App to be
available; it does not require user-supplied model API credentials. The automation is a research
handoff, not an operating-system scheduler or a broker integration.

For a manual run, place the cited request in the inbox and use these commands:

```bash
stock-research validate-input data/inbox/2026-07-21.json
stock-research generate --input data/inbox/2026-07-21.json
stock-research reports
stock-research report 2026-07-21
stock-research serve --port 8000
```

`validate-input` checks the JSON schema without fetching prices or writing a report. `generate`
reads the persisted active stock set, retrieves completed daily bars, builds the report, and prints
the three output paths. `reports` lists saved dates and statuses. `report YYYY-MM-DD` reads and
prints an already saved JSON report without fetching market data or creating report storage.
`serve` starts the local dashboard on `http://127.0.0.1:8000`; it binds only to loopback.

The complete CLI is:

```text
stock-research init [OUTPUT_PATH]
stock-research import-config INPUT_PATH
stock-research validate-input INPUT_PATH
stock-research generate --input INPUT_PATH
stock-research reports
stock-research report YYYY-MM-DD
stock-research serve --port 8000
```

There are no buy, sell, order, broker, or credential commands.

## Market-data provenance and gaps

For completed Shanghai and Shenzhen daily bars, the application uses Tencent A-share history
through AkShare. Beijing Stock Exchange daily K lines use the public data-only OpenTDX client.
Neither path requires an API key, account, broker connection, order, or trade operation; OpenTDX
is limited to its public daily-bar retrieval interface. Hong Kong history remains on the existing
provider path.

A public source can include a same-day intraday bar. The application filters every result to the
declared completed session before technical analysis. If a provider fails or its completed history
is insufficient, the report stays `partial` and shows a concise, source-neutral data gap. It does
not expose a hostname, URL, proxy detail, or raw network exception in report prose.

## Outputs and interpretation

Each manual or legacy run without a slot is saved below `<app-home>/reports/YYYY-MM-DD/` as
`report.json`, `report.md`, and `report.html`. Automatic pre-market reports are stored at
`<app-home>/reports/YYYY-MM-DD/pre-market/`, and automatic post-market reports are stored at
`<app-home>/reports/YYYY-MM-DD/post-market/`, so the two reports cannot overwrite each other. All formats retain the stock identity, report and generation dates, market state,
data-as-of dates, warnings, data gaps, disclaimer, analysis sections, short/medium/long horizons,
and source links. Markdown and HTML render daily volume and prior-day volume in shares (`股`) and
volume change as a percentage (`%`); JSON retains the corresponding numeric fields for machine
use. Both human-readable reports end with an all-stock table that summarizes each horizon's
conditional action, risk level, and confidence. SQLite stores the active configuration, report
history, and run records used by the CLI and dashboard.

Read the dates separately: `report_date` is the intended research day, `generated_at` is when the
request was assembled, and each market/research/technical `data_as_of` value identifies the last
data actually used. A holiday, suspension, delayed source, or unavailable quote can therefore make
the data-as-of date earlier than the report date.

`DailyRunRequest` can provide `market_sessions` facts for each configured market, including the
separate `beijing` market for BSE subjects. Each fact has a
`completed_session` date and `is_closed` boolean for the report date. Explicit request facts take
priority over the weekday fallback: a closed market with current prior-session data is shown as
`closed`, while missing or stale coverage remains `partial` or `unavailable`.

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

The available holding risk profiles are `conservative` (保守型), `balanced` (均衡型), and
`aggressive` (进取型). For non-low-confidence research views, the profile changes only the
conditional percentage cap for short / medium / long horizons:

- conservative: ≤5% / ≤10% / ≤15%
- balanced: ≤10% / ≤15% / ≤20%
- aggressive: ≤15% / ≤20% / ≤25%

These are research risk constraints, not capital assumptions, orders, or return estimates.
Any low-confidence view uses the tighter `≤5%` cap for all three horizons, regardless of the
configured profile.

## Failure recovery

- If the active set is empty, run `import-config` again with the intended YAML and confirm the same
  `STOCK_RESEARCH_HOME` is used by setup, manual commands, the dashboard, and Codex.
- If `validate-input` fails, correct the reported JSON field, timestamp, citation, or symbol
  mismatch. Do not invent evidence or bypass validation.
- If a run is `partial`, keep the valid output, then investigate every warning and per-stock data
  gap. Retry only after the missing source or completed market data is available.
- If generation fails, inspect the CLI error and the local run record. Run records are stored at
  `<app-home>/data/runs.sqlite3`, where `<app-home>` is the resolved `STOCK_RESEARCH_HOME` or the
  default `.stock-research` directory.
  `stock-research reports` lists generated reports, not failed run attempts.
  This copyable command opens the configured run database read-only and prints the 10 most recent
  report dates, statuses, stages, errors, and timestamps:

  ```powershell
  python -c "import os, sqlite3; from pathlib import Path; home=Path(os.environ.get('STOCK_RESEARCH_HOME', '.stock-research')).expanduser().resolve(); database=home/'data'/'runs.sqlite3'; connection=sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True); rows=connection.execute('SELECT report_date, status, stage, error_message, started_at, finished_at FROM runs ORDER BY started_at DESC LIMIT 10').fetchall(); print('\n'.join(' | '.join('' if value is None else str(value) for value in row) for row in rows) or 'no run records'); connection.close()"
  ```

  Use the reported stage and error to correct the input, configuration, filesystem, or data-access
  issue, then rerun the same validated request.
- If the dashboard port is occupied, choose another local port, for example
  `stock-research serve --port 8001`.

## Development validation

The repeatable integration coverage checks partial-report parity across JSON, Markdown, and HTML,
plus fake-client Hong Kong endpoint dispatch and normalized first/latest OHLCV rows without network
access.

```powershell
python -m pytest -v
python -m ruff check .
stock-research --help
```
