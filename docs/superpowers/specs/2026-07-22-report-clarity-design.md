# Report clarity design

**Date:** 2026-07-22

## Goal

Make the human-readable daily reports unambiguous about volume units and give the reader one
final, all-stock view of each conditional recommendation.

## Scope

- Markdown and HTML render `volume` and `previous_volume` in shares (`股`) and
  `volume_change_percent` as a signed percentage (`%`).
- JSON stays unchanged: its three fields remain numeric for downstream consumers.
- Markdown and HTML end with the same per-stock table for short, medium, and long horizons. Each
  cell contains the action, risk level, and confidence.
- Document the supported holding risk profiles and the low-confidence cap.

## Non-goals

- Do not change market-data providers, technical calculations, recommendation rules, persistence
  schema, or any broker/trading behavior.
- Do not imply that a report summary is an order or a return forecast.

## Acceptance criteria

- Unit tests prove Markdown and HTML use `股` and `%`, while JSON values remain numeric.
- Unit tests prove the final summary includes every stock and all three horizons.
- The existing 2026-07-22 report is safely re-rendered from its validated JSON without refetching
  market data.
