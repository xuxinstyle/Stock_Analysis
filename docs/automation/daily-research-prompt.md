# Codex daily A-share, BSE, and Hong Kong research handoff

Use this one shared document as the prompt body for both local Codex App automatic research
tasks in the `E:\Stock_Analysis` project. The 09:00 China Standard Time task must pass
`pre_market`; the 23:00 China Standard Time task must pass `post_market`. This is a
research-only workflow: it produces a `DailyRunRequest` JSON document and a local report; it
does not place trades.

## Safety and scope

- Never place orders, connect to brokers, or execute trades.
- Never assert return certainty or write an uncited material claim.
- Record data gaps rather than inventing information.
- 所有自动生成的研究摘要、事件说明和数据缺口解释必须使用简体中文；外文原始来源标题可作为引用元数据保留。
- Do not use or request API keys, credentials, or an operating-system scheduler.
- The local application retrieves completed A-share daily history through Tencent via AkShare and
  BSE daily K lines through public, data-only OpenTDX retrieval. These paths require no key,
  account, broker connection, trade, or order; Hong Kong retrieval is unchanged. A provider may
  return a same-day intraday bar, so rely only on the completed-session filtering performed by the
  local application.
- If daily-bar retrieval fails or lacks completed-session coverage, retain a concise, source-neutral
  data gap and a partial report. Do not copy a hostname, URL, proxy detail, or raw network error
  into the research input, report, or local-run note.
- Research only the active configured A-share, Beijing Stock Exchange (BSE), and Hong Kong subjects. Query the SQLite-backed persisted active stock list, not a YAML configuration file.
- The existing local application-service invocation below reads the same app home and repository used by `DailyRunService` and emits active symbol, name, market, industry, and optional holding-risk context:

  ```powershell
  python -c 'from stock_research.cli import active_stock_context; import json; print(json.dumps(active_stock_context(), ensure_ascii=False))'
  ```

  If the SQLite-backed list is empty or unavailable, stop and record that configuration is the
  blocking data gap; do not silently substitute the example configuration.
- Treat the result as research, not personalized investment advice. Do not change the
  configured stock list, source code, or prior reports.

## Automatic run mode (required)

The invoking automatic task must explicitly provide exactly one `run_slot` value. Never omit it
or infer it from the clock.

- `pre_market` (09:00 China Standard Time): use the last completed trading session before the
  report date for every market. Do not describe an incomplete current-day session as closed or
  complete.
- `post_market` (23:00 China Standard Time): first confirm that each applicable market has
  closed for the report date. 确认当日市场已经收市；only after that confirmation may its
  `completed_session` and `data_as_of` equal the report date. Cover that day's close, price
  change, volume, technical context, and intraday/post-market events. In all auto-generated prose,
  write the corresponding descriptions as Simplified Chinese: 当天收盘、涨跌、成交量、技术面，以及盘中和盘后事件。
- Safe session fallback: if same-day closing status or completed daily data cannot be verified,
  retain a Simplified Chinese data-gap explanation, use the last verifiable session, and do not
  claim same-day completed coverage. 保留数据缺口，并使用最后可验证会话。
- Event fallback: An unverified or conflicting event must remain an explicit Simplified Chinese event/research data gap and must not change a confirmed `post_market` same-day session with verified daily data. 未核实或存在冲突的事件必须保留为明确的简体中文事件或研究数据缺口，不得改变已确认收市且日线数据已核实的当日会话。

For either mode, auto-generated research summaries, event descriptions, and data-gap explanations
must be Simplified Chinese. Preserve the source title and URL exactly as supplied by the source.

## Research procedure

1. Read every active configured symbol, name, market, industry, and holding context. Cover every
   configured market: A-share (`SH.` / `SZ.`), Beijing Stock Exchange (`BJ.`), and Hong Kong (`HK.`), when present.
2. Resolve each market's completed session by `run_slot`. For `pre_market`, use the last completed
   trading session before the report date. For `post_market`, a confirmed trading market may set `completed_session` and `data_as_of` to `report_date` with `is_closed` set to `false`. For `post_market`, a holiday/non-trading market or an unverified close or completed daily data must use the last verifiable prior session. Record one `market_sessions` entry for each configured
   market with its `completed_session` and `is_closed` status on the report date. Set `is_closed`
   to `true` only for a market that did not trade on the report date. A closed market must use its
   last verifiable prior session. Label holidays, suspensions, delayed quotes, and unavailable data
   as Simplified Chinese data gaps; never present an
   incomplete session as a completed one.
3. Use web search and inspect the source pages. Prefer primary sources in this order when
   available: exchange filings and announcements, company investor-relations disclosures,
   government or regulator publications, and official market or product-price publications.
   Use reputable secondary reporting only when a primary source is unavailable, and give it
   lower credibility.
4. For each configured symbol, research and cite:
   - exchange/company disclosures, earnings or operating context, and company news;
   - price and volume context for the completed session resolved by `run_slot`;
   - industry conditions, sector demand/supply, and sector/product prices;
   - Chinese, Hong Kong, or other applicable policy and regulatory developments;
   - US peers, US market drivers, and international transmission channels that could affect
     the subject or its industry.
5. For every material claim, retain an evidence record with its title, URL, source name,
   publication time, retrieval time, direction, credibility, category, summary, and affected
   symbol. Use `null` for an unavailable publication time. `credibility` is `3` for a primary source, `2` for a reputable
   secondary source, and `1` for a low-confidence source. Use only these categories:
   `company`, `industry`, `policy`, `news`, `international`, and `product_price`.

Every evidence record must include title, URL, source name, publication time, retrieval time, direction, credibility, category, summary, and affected symbol.

For recommendation generation, the application applies a horizon-specific freshness filter anchored
to the stock's latest completed trading day: short-term recommendations use only evidence published
and events occurring in the latest 5 calendar days; medium-term uses the latest 3 calendar months;
long-term uses the latest 2 calendar years. Retrieval time does not refresh an old source. Keep
older material in the traceable source archive when useful, but do not cite it or use it as a
decision input for a shorter horizon. When a horizon has no eligible evidence, preserve an explicit
Simplified-Chinese data gap rather than substituting older material.
6. Reconcile sources before writing. Explicitly label an item `未核实` when it cannot be
   confirmed, and label the evidence or summary `存在冲突` when credible sources materially
   disagree. State what conflicts and what would resolve it. Record data gaps rather than inventing
   information.

## Required JSON output

Write exactly one UTF-8 JSON file, for example
`.stock-research/input/daily-research-request-YYYY-MM-DD.json`, that validates as
`DailyRunRequest`. Do not add recommendation fields to this request: the local generator
derives recommendations from the cited research.

```json
{
  "report_date": "YYYY-MM-DD",
  "run_slot": "pre_market or post_market",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+08:00",
  "market_sessions": [
    {
      "market": "a_share, beijing, or hong_kong",
      "completed_session": "YYYY-MM-DD",
      "is_closed": false
    }
  ],
  "research_inputs": [
    {
      "symbol": "SH.600000, SZ.000001, BJ.920808, or HK.00700",
      "data_as_of": "YYYY-MM-DD",
      "fundamental_summary": "cited company and financial/operating context, or an explicit gap",
      "industry_summary": "cited industry and price/volume context, or an explicit gap",
      "policy_summary": "cited policy/regulatory context, or an explicit gap",
      "news_summary": "cited company/news context, or an explicit gap",
      "international_summary": "cited US-peer and international-transmission context, or an explicit gap",
      "product_price_summary": "cited sector/product-price context, or an explicit gap",
      "events": [],
      "evidence": []
    }
  ]
}
```

Create one `StockResearchInput` for every active configured symbol. Fill all six research
summaries and events for each subject. Each summary must be nonblank; a nonblank gap statement
is required when evidence is unavailable. Do not create a fabricated citation to make a summary
appear complete. Include at most one `market_sessions` entry for each configured market. For
`post_market`, use `report_date` with `is_closed: false` only for a confirmed trading market with
verified completed daily data; otherwise use the last verifiable prior session and a Simplified
Chinese data gap. Set `is_closed` to `true` only when that market did not trade on `report_date`.

For every `evidence` entry include all of these schema fields:

```json
{
  "title": "source title",
  "url": "https://...",
  "source_name": "publisher or institution",
  "published_at": "YYYY-MM-DDTHH:MM:SS+08:00 or null",
  "retrieved_at": "YYYY-MM-DDTHH:MM:SS+08:00",
  "category": "company|industry|policy|news|international|product_price",
  "direction": "positive|neutral|negative",
  "credibility": 1,
  "summary": "at least 20 characters, including any 未核实/存在冲突 label",
  "symbols": ["the configured symbol"]
}
```

For each event, include `title`, `occurred_at`, `direction`, `summary`, `symbols`, and `scope`.
Set `is_confirmed` to `true` only when it has a cited source, and then also include
`citation_title` and `citation_url`. Otherwise set `is_confirmed` to `false` and say
`未核实` in the event summary. Use `local` only for an event on the configured subject;
use `international` for overseas or peer context. International events are context only and must
never directly determine a buy, reduce, or avoid view. Never invent citations.

## Local validation and report handoff

1. Validate the saved JSON before generating:

   ```powershell
   stock-research validate-input .\.stock-research\input\daily-research-request-YYYY-MM-DD.json
   ```

2. If validation fails, correct only schema, citation, timestamp, or explicitly labelled
   data-gap issues, then validate again. Do not bypass validation or replace missing evidence
   with invented content.
3. Generate the local report only after validation succeeds:

   Before this step, ensure the local automation process has a user-level
   `STOCK_RESEARCH_FEISHU_WEBHOOK_URL` environment variable configured for the Feishu V2 custom
   robot. Never print, write, request, or embed the Webhook value in this prompt, a report, source
   code, configuration, or the local-run note. `generate` saves the report first, then sends every
   report section to Feishu: the market overview/preamble, one message per company section, and a
   separate final all-symbol action-summary message. It safely numbers and splits only overlong
   individual sections. If that notification fails,
   keep the saved report, record the failure, and do not invent a successful delivery.

   ```powershell
   stock-research generate --input .\.stock-research\input\daily-research-request-YYYY-MM-DD.json
   ```

4. Inspect the printed JSON, Markdown, and HTML report paths. Confirm each configured subject
   has the expected research sections, source links, data-gap/conflict labels, and short,
   medium, and long recommendations. Each recommendation must include trigger,
   observation/target, invalidation, position limit, risk, and confidence. If a source or
   required input is missing, leave the documented data gap visible rather than editing the
   generated report or claiming certainty.

Every short, medium, and long recommendation must include trigger, observation/target, invalidation, position limit, risk, and confidence.

End with a short local-run note listing the report paths, 未核实/存在冲突 items, and
remaining data gaps. Do not send orders, broker messages, or investment instructions.
