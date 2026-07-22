# Daily Market Data Provider Replacement Design

## Context

The daily research flow currently obtains Shanghai, Shenzhen, and Beijing daily bars through
AkShare's `stock_zh_a_hist`, which resolves to the Eastmoney `push2his.eastmoney.com` endpoint.
On 2026-07-22 the endpoint became unavailable on this workstation. The report must continue to
degrade safely, but the primary data path must no longer depend on that endpoint.

The active configuration contains five Shanghai/Shenzhen subjects and one Beijing subject
(`BJ.920808`). The replacement therefore must preserve both mainland A-share and Beijing
coverage, must end at the declared completed session, and must supply at least 30 daily bars.

## Goals and Constraints

- Remove Eastmoney `push2his` from the A-share and Beijing historical-daily-bar path.
- Keep `MarketDataProvider` and downstream report interfaces stable.
- Use only read-only, public, no-key market-data calls. Do not access broker accounts, trading
  endpoints, order functionality, or credentials.
- Preserve date, OHLC, volume, and adjustment semantics before technical indicators run.
- Keep Hong Kong behavior unchanged; it is outside this specific endpoint replacement and there
  are no active Hong Kong subjects.
- Present concise user-facing gaps. Raw transport diagnostics belong only in diagnostic logging or
  persisted run detail, not in recommendation rationale or Markdown/HTML report prose.

## Options Considered

1. **Tencent-only:** AkShare's Tencent daily-history call works for Shanghai/Shenzhen but did not
   return daily bars for `BJ.920808` or its prior code. It would silently regress Beijing coverage
   and is rejected.
2. **Selected design: market-specific data-only providers:** Tencent is the Shanghai/Shenzhen
   daily provider; a separately verified, data-only Beijing provider supplies `BJ.920808` daily
   bars. The OpenTDX project is a candidate because its published capability list includes Beijing
   daily K lines, but it is not accepted until a local live probe proves 30+ completed, correctly
   dated bars for `BJ.920808` without credentials or trading APIs.
3. **Commercial key-based API:** potentially broad coverage but conflicts with the no-key safety
   contract, so it is excluded.

## Architecture

`AkShareMarketDataProvider` becomes a dispatcher rather than an Eastmoney wrapper:

- `Market.A_SHARE` dispatches to AkShare `stock_zh_a_hist_tx`, passing an explicit `sh` or `sz`
  vendor symbol, requested completed-session date range, and `qfq` adjustment.
- `Market.BEIJING` dispatches to a narrow Beijing daily-bar adapter. The adapter may call only the
  read-only K-line API of the accepted provider; it cannot import or expose trading operations.
- `Market.HONG_KONG` retains its existing adapter unchanged.
- Each adapter normalizes source fields to `date`, `open`, `high`, `low`, `close`, and `volume`.
  The Tencent field emitted as `amount` is accepted only after the live probe and a fixture assert
  establish that it is the source's share-volume field for this endpoint.
- The existing completed-session value remains the `end` argument. No provider may request or use
  an intraday bar dated on the report date.

The Beijing adapter has an explicit rollout gate:

1. Probe the candidate with `BJ.920808` for the declared completed session.
2. Verify 30 or more normalized rows; the last date must equal the completed session, OHLC and
   volume must be non-negative, and adjustment behavior must be documented.
3. Only then wire it into normal report generation. A failed probe leaves the existing safe partial
   report behavior in place rather than substituting an unverified price.

## Failure Handling and Reporting

- Provider network, parsing, or insufficient-history failures are converted to
  `MarketDataUnavailable`.
- `ReportBuilder` retains the current conservative fallback: one short, medium, and long `watch`
  recommendation with low confidence and high risk when local price data is unavailable.
- The report-facing gap is a concise source/status message such as “沪深历史行情源暂不可用” or
  “北交所历史行情源未通过日期校验”. It must not include URLs, proxy stack traces, or raw exceptions.
- The diagnostic detail is retained separately for troubleshooting; it must never be represented as
  investment rationale or a source citation.

## Tests and Acceptance Criteria

- A failing test first proves Shanghai/Shenzhen dispatch uses Tencent and never calls
  `stock_zh_a_hist`.
- A failing test first proves Beijing dispatch uses the dedicated adapter and receives normalized
  `BJ.920808` bars ending on the declared completed session.
- Tests cover Tencent symbol mapping, normalized columns, 30-bar minimum, completed-session
  cutoff, concise data-gap rendering, and no unhandled request exception.
- A live, read-only probe validates the five active Shanghai/Shenzhen symbols and `BJ.920808`.
- Generated JSON, Markdown, and HTML reports remain schema-valid and preserve source links.
- Full test suite, Ruff lint/format, and `git diff --check` pass.
- Production A-share/Beijing daily-bar code contains no Eastmoney `push2his` dependency; no API
  key, account, broker connection, or trade operation is introduced.

## Rollout

1. Add provider fakes and failing dispatch/rendering tests.
2. Add the smallest provider adapters and dependency needed for the verified Beijing source.
3. Run unit tests, then real completed-session probes for all six active subjects.
4. Regenerate the daily research input and report only if those probes pass; otherwise persist a
   concise partial report with the verified source-specific gap.
5. Update the automation prompt and README with provider provenance, limitation, and recovery
   behavior.
