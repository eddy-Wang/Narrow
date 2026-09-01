# Trace viewer

[Project home](../README.md) · [Trace JSON format](../docs/TRACE_JSON_FORMAT.md)

This optional local viewer shows how a target product moves through intent
understanding, retrieval, fusion, filtering, reranking, and the final Top 10.
No evaluation data is bundled. Select a generated `trace.json` in the browser,
or follow a `runId` link from the local workbench API.

## Run

From the repository root:

```powershell
npm --prefix trace-visualizer ci --no-audit --no-fund
npm --prefix trace-visualizer run dev
```

Open http://127.0.0.1:3000 and choose a local `trace.json`. The selected file
is parsed in the browser and is not uploaded.

## Files

| Path | Purpose |
|---|---|
| `app/page.tsx` | Trace selection, navigation, filters, and diagnostic views |
| `app/globals.css`, `app/layout.tsx` | Shared styling and page metadata |
| `lib/trace.ts` | Portable trace validation and legacy-format compatibility |
| `components/ui/` | Five UI primitives used by the page |
| `scripts/build-diagnostics.py` | Convert a traced evaluation into viewer diagnostics |
| `scripts/build-trace-preview.py` | Create small preview fixtures |
| `scripts/tests/` | Python and Node format checks |
| `public/favicon.svg` | Viewer icon |
| `package.json`, `package-lock.json` | Scripts and locked dependencies |
| `vite.config.ts`, `next.config.ts`, `tsconfig.json` | Vinext/Vite/TypeScript configuration |
| `.oxlintrc.json`, `.oxfmtrc.json` | Lint and format configuration |

## Verify

```powershell
node --experimental-strip-types --test trace-visualizer/scripts/tests/trace-format.test.mjs
npm --prefix trace-visualizer run build
```

Build output is ignored. The viewer accepts current `shopping-agent.trace` v1
files and validates legacy diagnostics without shipping historical run data.
