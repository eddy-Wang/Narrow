# Shopping Copilot workbench

[Project home](../README.md) · [Testing and generated artifacts](../docs/TESTING.md)

This Vue 3 / Vite application provides bilingual chat, three evaluation modes,
run history, model settings, and links into the local trace viewer. The HTTP API
is implemented by
[`shopping_agent.web`](../techjam-conversational-search/src/shopping_agent/web.py).
The workbench is optional and is not required for command-line scoring.

## Start

Requirements: Python 3.12, uv, and Node.js 22.13 or a compatible newer release.
Run from the repository root.

macOS or Linux:

```bash
./scripts/run_demo.sh
```

Windows PowerShell:

```powershell
.\scripts\run_demo.ps1
```

Starting the pages and importing an existing `trace.json` does not require a
catalog or API key. For real chat or new evaluations, provide
`techjam-conversational-search/data/catalog.jsonl` as described in the
[data guide](../techjam-conversational-search/data/README.md). An existing
catalog can be selected explicitly:

```bash
./scripts/run_demo.sh --catalog-path /absolute/path/to/catalog.jsonl
```

```powershell
.\scripts\run_demo.ps1 -CatalogPath 'C:\path\to\catalog.jsonl'
```

The launcher installs missing dependencies, starts three localhost-only
services, and writes new runs and server logs under the ignored `demo_runs/`
directory. Use `--skip-install` or `-SkipInstall` only after dependencies are
installed. Press Ctrl+C to stop all services.

| Service | Address | Purpose |
|---|---|---|
| Workbench | http://127.0.0.1:5173 | Chat, evaluation, history, and settings |
| Local API | http://127.0.0.1:8000 | Agent and evaluation adapter |
| Trace viewer | http://127.0.0.1:3000 | Local `trace.json` inspection |

## Behavior

- Chat calls `ShoppingAgent.start_session/chat`; catalog details remain on the backend.
- Native evaluation uses the bundled traced evaluator. TechJam and Realistic use the optional user simulator.
- Settings apply to later chat and evaluation runs; changing them resets in-memory chat state.
- One evaluation runs at a time. Evaluation history survives service restarts; chat history does not.
- CLI results are not registered automatically in browser history. Import their `trace.json` directly.
- The trace viewer reads selected files in the browser and does not upload them.

The workbench defaults to local understanding and the precise baseline so it
can open without paid calls. Select and save **DeepSeek + LambdaMART** for the
same primary configuration used by `run_evaluation.ps1`.

## DeepSeek and safety

Configure `DEEPSEEK_API_KEY` in `techjam-conversational-search/.env` before
selecting DeepSeek. Connection tests, online chat, and online evaluation can
incur API charges. The key and Base URL stay on the backend; the browser cannot
read the key or redirect it to another host. Cross-site writes and non-local
hosts are rejected. This demo is not configured for public or LAN exposure.

## Files

| Path | Purpose |
|---|---|
| `src/views/` | Page-level UI |
| `src/stores/` | Chat, evaluation, and settings state |
| `src/api.ts`, `src/types.ts` | HTTP client and shared contracts |
| `src/locales/` | English and Chinese copy |
| `src/test/` | Vitest behavior checks |
| `public/` | Referenced hero and social-preview images |
| `package.json`, `package-lock.json` | Scripts and locked dependencies |
| `vite.config.ts`, `vitest.config.ts`, `tsconfig*.json` | Build, test, and TypeScript configuration |

## Verify

```powershell
npm test
npm run build
```

Run these commands from `demo-frontend/`. Build output is written to ignored
`dist/`; the local API can serve it after a successful build.
