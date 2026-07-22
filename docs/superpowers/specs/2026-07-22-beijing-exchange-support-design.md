# Beijing Stock Exchange Support Design

## Goal

Allow the local research workflow to configure, validate, research, and report current Beijing Stock Exchange (BSE) securities alongside Shanghai, Shenzhen, and Hong Kong subjects.

## Scope

- Introduce `Market.BEIJING` with persisted value `beijing`.
- Accept only the current BSE symbol notation `BJ.9xxxxx`; this keeps the configured symbol explicit and rejects legacy pre-code-conversion forms such as `BJ.872808`.
- Extend every subject-symbol validation boundary: stock configuration, daily research inputs, evidence-symbol checks, and events.
- Query BSE daily bars through the existing AkShare mainland historical-bar interface with the six-digit BSE code. Normalization, completed-bar minimums, and data-gap handling remain unchanged.
- Produce a separate `beijing` market-session/status entry so a BSE closure or stale BSE data cannot be presented as a completed Shanghai/Shenzhen session.
- Surface BSE as a selectable Web configuration market and document `BJ.920808` in the local configuration and daily-automation contracts.

## Non-goals

- No trading, broker connectivity, credentials, price targets, or automated orders.
- No support for legacy BSE codes, US securities, or a second market-data provider.
- No change to the existing configured holding values; adding the user's requested securities is a separate post-validation configuration action.

## Architecture

`Market` remains the single market discriminator. Adding `BEIJING` makes the SQLite repository, Web form, request/session models, report builder, and templates enumerate the market naturally. The explicitly enumerated report-status loop gains BSE so coverage is visible as its own status.

The AkShare provider strips `BJ.` to `920808`, identifies the exchange as `bj`, and dispatches BSE to `stock_zh_a_hist`, the same normalized mainland daily-bar shape used for Shanghai and Shenzhen. An unavailable or incomplete vendor response continues to become a per-symbol data gap rather than a fabricated price.

## Data contract

| Subject | Persisted market | Required symbol |
| --- | --- | --- |
| Shanghai/Shenzhen | `a_share` | `SH.######` or `SZ.######` |
| Beijing | `beijing` | `BJ.9#####` |
| Hong Kong | `hong_kong` | `HK.#####` |

`DailyRunRequest.market_sessions` may contain one `beijing` entry. Its `completed_session` must precede `report_date`, following the existing validation rule.

## Tests and verification

- First add tests that demonstrate BSE configuration, input/evidence validation, AkShare dispatch, Web form persistence, and distinct BSE report status.
- Run each new test before implementation and confirm the expected feature-missing failure.
- Implement the smallest changes to make those tests pass, then run the full pytest suite, Ruff checks, formatting check, and `git diff --check`.
- Only after code verification, atomically configure the requested current-code BSE security with the confirmed holdings; no ambiguous cost value is persisted.

## Configuration follow-up

The requested six-stock list will use `BJ.920808` for 曙光数创. 华特气体's confirmed holding cost is `146.485`; it will be persisted as an exact decimal only after code verification completes.
