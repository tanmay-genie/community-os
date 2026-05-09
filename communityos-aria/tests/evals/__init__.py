"""ARIA eval suite — golden test cases + runner + scoreboard.

The eval suite measures ARIA's quality on real product flows so prompt /
classifier / tool changes can be validated against a stable baseline.

Two modes:
  fast — LLM stubbed; measures intent routing, tool selection, structured
         prefixes, currency hygiene, English-only constraint
  full — real Gemini calls (costs $); measures response quality end-to-end

Run:
  pytest tests/evals/ -v          # fast mode (default)
  ARIA_EVAL_FULL=1 pytest tests/evals/ -v   # full mode (uses live LLM)
"""
