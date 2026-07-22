# Report clarity implementation plan

**Date:** 2026-07-22

1. Add failing renderer tests for volume units, JSON numeric preservation, and a final multi-stock
   recommendation summary.
2. Add display-only formatters and a shared recommendation-summary label in `ReportStore`; expose
   the label to the dashboard template and render the final table in Markdown and HTML.
3. Document the three risk profiles and low-confidence override, re-render the existing report
   from validated JSON, then run the full suite, static checks, independent review, commit, and
   push to `main`.
