# Contributing to Narrow

Thank you for helping improve Narrow. Contributions are welcome in retrieval,
ranking, conversational state, evaluation, observability, documentation, and
developer experience.

## Before opening a change

1. Search existing issues and discussions.
2. Open an issue for behavior changes or new public interfaces.
3. Keep pull requests focused and include a reproducible test.
4. Do not include API keys, private catalogs, user conversations, or generated
   traces containing sensitive data.

## Development setup

```bash
uv sync --locked --project narrow-shopping-agent \
  --extra web --extra ltr --extra openai --group dev
PYTHONPATH="narrow-shopping-agent:narrow-shopping-agent/src:user-simulator/src" \
  uv run --project narrow-shopping-agent python -m pytest \
  -c narrow-shopping-agent/pyproject.toml \
  narrow-shopping-agent/tests user-simulator/tests -q
```

Frontend changes should also run:

```bash
npm --prefix demo-frontend ci --no-audit --no-fund
npm --prefix demo-frontend test -- --run
npm --prefix demo-frontend run build

npm --prefix trace-visualizer ci --no-audit --no-fund
node --experimental-strip-types --test \
  trace-visualizer/scripts/tests/trace-format.test.mjs
npm --prefix trace-visualizer run build
```

## Pull-request checklist

- Tests cover the changed behavior.
- User-facing behavior and configuration are documented.
- New traces or fixtures contain no secrets or private user data.
- Ranking changes report the evaluation set, metrics, and comparison baseline.
- Provider changes retain a deterministic offline test path.

Maintainers may request smaller commits, additional regression coverage, or a
trace showing how state and ranking changed.
