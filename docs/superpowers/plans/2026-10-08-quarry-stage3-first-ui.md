# Quarry Stage 3: First UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a browser UI on the Stage 2 server so a researcher can open the printed link, start a session, type a prompt, watch the step land, and interact with the resulting view. The view runs agent-written TSX inside a sandboxed iframe with no network access, talking to the host only through postMessage. Two built-ins ship: an AG Grid table and a Lightweight Charts time series. This is the milestone to put in front of a researcher.

**Architecture:** `web/` is one Vite project with two HTML entries. `index.html` is the host app (React 19, React Query v5, shadcn/ui on Tailwind 4): sessions rail, step column, prompt box, status polling, code drawer, interrupt, restart. `runtime.html` is the iframe runtime: Sucrase transpiles TSX at mount time, an allowlisted `require` table resolves imports (React, the design system, `@quarry/hooks`, and lazily loaded chart chunks), an error boundary reports mount failures. A postMessage bridge with correlation ids is the only link between the two; the host alone holds the bearer token and forwards `query` and `schema` requests to the Stage 2 endpoints. The web build lands in `src/quarry/static/` (gitignored, included in the wheel as an artifact) together with `transpile-check.mjs`, the node bundle Stage 2's `default_transpiler` already looks for, and `runtime-manifest.json`, which tells the server which chart libraries this bundle can resolve. Server additions are small: snapshot recording for view state, a repair field on step requests, and the runtime manifest gate.

**Tech Stack:** Node 24, npm, Vite 8, React 19.3, TypeScript 6 strict, Tailwind 4.3 via `@tailwindcss/vite`, shadcn 4.21 (`base-nova` style on `@base-ui/react`), `@tanstack/react-query` 5.104, `sucrase` 3.35, `ag-grid-community` + `ag-grid-react` 36.2, `lightweight-charts` 5.2, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`, `esbuild` (dev, bundles the node checker), vitest 5 + `@testing-library/react` 16 + jsdom 29, prettier 3.9. Python side: Stage 2 package as built on branch `claude/quarry-stage2-server-agent-66853b`, plus `pytest-playwright` 0.10 for the end-to-end test.

**Spec:** `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 4, 5 View/Step, 9 Frontend, 12 Security, 13 Error handling, 14 Testing, 15 stage 3). Stage 2 interfaces as implemented: `src/quarry/server/app.py`, `models.py`, `service.py`, `store.py`, `agent/tools.py`, `agent/context.py`, `agent/transpile.py`, `components/library.py`.

## Global Constraints

- Stage 1 and Stage 2 Global Constraints still apply to all Python (typing, ruff, mypy strict, no bare excepts, pathlib, bare Conventional Commit types, no attribution trailers).
- TypeScript: `strict` on, no `any` (use `unknown` and narrow), `interface` for props, no `React.FC`, discriminated unions for request state, `useEffect` only where a DOM library or a window listener needs it (the bridge listeners and the Lightweight Charts container are the legitimate cases). Every file under 250 lines. Prettier on every file (`npm run format`), `tsc -b` clean, vitest green.
- Library versions above were read from a fresh `npm create vite` + `npx shadcn@latest init` on 2026-10-08. The code in this plan targets those APIs: AG Grid 36 needs `ModuleRegistry.registerModules([AllCommunityModule])` and the `theme` prop (no CSS import); Lightweight Charts 5 uses `chart.addSeries(LineSeries, …)`; shadcn 4 components import from `@base-ui/react/*` and `cn` from the `cn` package. Do not downgrade to remembered APIs.
- The runtime iframe is `sandbox="allow-scripts"` (never `allow-same-origin`) with a meta CSP of `default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src data:; font-src 'self'; connect-src 'none'`. `'unsafe-eval'` is required because Sucrase output is evaluated with `new Function`; the jail is the sandbox plus `connect-src 'none'`, not the eval ban. The iframe has an opaque origin, so host to runtime `postMessage` uses target origin `"*"`, and the host trusts a message only when `event.source === iframe.contentWindow`. Never check `event.origin`; it is the string `"null"`.
- The token is read from `location.hash` once and kept in memory. The hash stays in the URL so a reload keeps working; fragments never reach the server. No cookie, no `localStorage`.
- The host is the only party holding the token. The runtime never sees a URL, a token, or `fetch`.
- A view component's default export receives exactly one prop, `datasets: string[]`, the names passed to `render_view` or `write_view` in order. Built-ins read `datasets[0]`.
- Snapshot recording lands now (`useViewState` posts `stateChanged`, the host stores it); the scrubber UI over snapshots is Stage 4.
- The web build must run before `uv build`; the wheel is only correct with `src/quarry/static/index.html` present. CI builds web first.

## Design tokens

Brief: a dense working tool for quant researchers, opened from an SSH terminal, used for hours. The memorable element is the step column read as a ledger: no cards, no shadows, each step marked by its index in the left margin and a thin vertical status rule beside it. Everything else stays quiet.

- Color (light only in Stage 3; the shadcn `.dark` block stays as generated for later): background `#EEF0F2` (limestone), panel `#FFFFFF`, ink `#1C2127`, secondary text `#5C6670`, hairline `#D5D9DE`, accent `#1E6E63` (serpentine: running state, primary action, links), error `#9A3B2E` (iron oxide), interrupted `#B8860B` (mica).
- Type: IBM Plex Sans for the interface, IBM Plex Mono for code drawers and numeric table cells. Base 14px, line height 1.5, scale 12 / 14 / 16 / 20 / 28. Sentence case everywhere, no uppercase labels, no eyebrow labels.
- Layout, left aligned throughout:

```
┌─────────────┬────────────────────────────────────────────────────┐
│ Sessions    │  1 │ prompt text                                   │
│ ▸ Untitled  │    │ status line           duration     datasets  │
│   Momentum  │    │ ┌──────────────────────────────────────────┐  │
│             │    │ │ view (iframe, 420px)                     │  │
│ New session │    │ └──────────────────────────────────────────┘  │
│             │    │ ▸ code                                        │
│             │  2 │ prompt text                                   │
│             │    │ ...                                           │
│             ├────────────────────────────────────────────────────┤
│             │ ┌──────────────────────────────────────┐ [Run]     │
│             │ │ Ask about the data                   │           │
└─────────────┴──────────────────────────────────────────────────────┘
```

Rail 232px, step column max width 880px with a 32px gutter, prompt box pinned to the bottom of the column. The status rule is the only coloured element on a step: serpentine while running, hairline grey when ok, iron oxide on error, mica when interrupted. Views are set flush inside the column between two hairlines. Buttons say what they do: "Run", "Stop", "Restart kernel", "Fix this view", "New session".

Checked against the generic default: no cream background, no serif display, no cards with the same radius and shadow, no uppercase eyebrows, no middle dots, no arrows in button text, no monospace for small labels (mono is reserved for code and numbers).

## Review Focus

1. A generated component imports a module outside the allowlist. Expected: the runtime posts `error` with the message naming the module and the allowed list, the host shows it in the view slot with a "Fix this view" button, nothing hangs. Pinned in Task 4 and Task 12.
2. The runtime's CSP `'self'` under an opaque sandbox origin. Expected: Chromium resolves `'self'` from the document URL, so the runtime's chunks and CSS load. Pinned by the Playwright test in Task 12. If chunks fail to load, the fallback is an explicit loopback host-source with a port wildcard, `script-src 'self' http://127.0.0.1:* http://localhost:*` (same for `style-src` and `font-src`); a response header resolves `'self'` exactly as the meta tag does, so that is not a fallback. The wildcard stays loopback-only and does not loosen the jail.
3. A query returns `truncated: true`. Expected: the data table shows a banner with the row count and the cap. Pinned in Task 8.
4. Status reports the kernel dead. Expected: the step column shows a banner with "Restart kernel"; restart replays and the banner clears. Pinned in Task 11.
5. The page is reloaded while a step is running. Expected: the token survives, the session reloads with the running step in place, polling resumes, the prompt box stays disabled until the step finishes. Pinned in Task 10.
6. A view's `stateChanged` arrives for a step whose file is already on disk. Expected: the snapshot is appended atomically to that step's JSON and `GET /sessions/{id}` shows it. Pinned in Task 9.

---

### Task 1: Web scaffold, tokens, build into the package

**Files:**

- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/tsconfig.app.json`, `web/tsconfig.node.json`, `web/vitest.config.ts`, `web/.prettierrc`, `web/.prettierignore`, `web/components.json`, `web/index.html`, `web/runtime.html`, `web/tools/transpile-check.ts` (placeholder), `web/src/runtime/libraries.ts`, `web/src/host/main.tsx`, `web/src/host/App.tsx`, `web/src/runtime/main.tsx`, `web/src/styles/tokens.css`, `web/src/host/index.css`, `web/src/runtime/index.css`, `web/src/test/setup.ts`, `web/src/lib/utils.ts`
- Create (generated by shadcn): `web/src/components/ui/{button,badge,textarea,separator,scroll-area,tooltip,input,select,tabs}.tsx`
- Modify: `pyproject.toml` (wheel artifacts), `.gitignore` (already has `web/node_modules/`, `web/dist/`, `src/quarry/static/`; verify)

**Interfaces:**

- Produces: `npm run build` writes `src/quarry/static/{index.html,runtime.html,assets/*}`; `npm run check`, `npm test`, `npm run format` scripts; `@/` alias to `web/src`; `@quarry/hooks` alias to `web/src/runtime/hooks.ts`; `@builtin/` alias to `src/quarry/components/builtin`.
- Consumes: `create_app` serving `static/` when `index.html` exists (Stage 2 `app.py` line 159).

- [ ] **Step 1: Scaffold**

```bash
cd ~/workspace/quarry
npm create vite@latest web -- --template react-ts
cd web
rm -rf src/assets src/App.css public
npm install tailwindcss @tailwindcss/vite @tanstack/react-query sucrase ag-grid-community ag-grid-react lightweight-charts @fontsource/ibm-plex-sans @fontsource/ibm-plex-mono
npm install -D vitest @testing-library/react @testing-library/dom @testing-library/user-event jsdom prettier esbuild
```

- [ ] **Step 2: Configure TypeScript**

Replace `web/tsconfig.app.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "esnext",
    "types": ["vite/client"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noUncheckedIndexedAccess": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"],
      "@quarry/hooks": ["./src/runtime/hooks.ts"],
      "@builtin/*": ["../src/quarry/components/builtin/*"]
    }
  },
  "include": ["src", "../src/quarry/components/builtin/**/*.tsx"]
}
```

Add the same `baseUrl` and `paths` to `web/tsconfig.json` under `compilerOptions` (shadcn reads them). Leave `tsconfig.node.json` as generated but add `"vitest.config.ts"`, `"tools/**/*.ts"` and `"src/runtime/libraries.ts"` to its `include` (the Vite config imports that file, and `tsc -b` refuses imports outside the project's file list).

- [ ] **Step 3: Vite config with two entries and the manifest plugin**

`web/vite.config.ts`:

```ts
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { RUNTIME_LIBRARIES } from "./src/runtime/libraries";

const root = import.meta.dirname;
const outDir = path.resolve(root, "../src/quarry/static");
const apiPort = process.env.QUARRY_PORT ?? "8765";

function runtimeManifest(): Plugin {
  return {
    name: "quarry-runtime-manifest",
    closeBundle() {
      mkdirSync(outDir, { recursive: true });
      writeFileSync(
        path.join(outDir, "runtime-manifest.json"),
        JSON.stringify({ libraries: RUNTIME_LIBRARIES }, null, 2),
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), runtimeManifest()],
  resolve: {
    alias: {
      "@": path.resolve(root, "./src"),
      "@quarry/hooks": path.resolve(root, "./src/runtime/hooks.ts"),
      "@builtin": path.resolve(root, "../src/quarry/components/builtin"),
    },
  },
  server: {
    fs: { allow: [path.resolve(root, "..")] },
    proxy: {
      "/sessions": `http://127.0.0.1:${apiPort}`,
      "/healthz": `http://127.0.0.1:${apiPort}`,
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: path.resolve(root, "index.html"),
        runtime: path.resolve(root, "runtime.html"),
      },
    },
  },
});
```

`web/src/runtime/libraries.ts` (ids match `src/quarry/agent/guide.md` headings):

```ts
export const RUNTIME_LIBRARIES = ["ag-grid", "lightweight-charts"] as const;
export type RuntimeLibrary = (typeof RUNTIME_LIBRARIES)[number];
```

- [ ] **Step 4: Scripts, prettier, vitest**

`web/package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build && npm run build:checker",
    "build:checker": "esbuild tools/transpile-check.ts --bundle --platform=node --format=esm --outfile=../src/quarry/static/transpile-check.mjs",
    "check": "tsc -b && prettier --check .",
    "format": "prettier --write .",
    "test": "vitest run",
    "preview": "vite preview"
  }
}
```

`web/.prettierrc`: `{}`. `web/.prettierignore`: `node_modules` (the build output lives outside `web/`, so prettier never sees it).

`web/vitest.config.ts`:

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";

const root = import.meta.dirname;

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(root, "./src"),
      "@quarry/hooks": path.resolve(root, "./src/runtime/hooks.ts"),
      "@builtin": path.resolve(root, "../src/quarry/components/builtin"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`web/src/test/setup.ts`:

```ts
import "@testing-library/dom";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
```

- [ ] **Step 5: shadcn init and tokens**

```bash
cd web
npx shadcn@latest init -d -y
npx shadcn@latest add -y button badge textarea separator scroll-area tooltip input select tabs
```

`init` rewrites `src/index.css`. Move its content to `web/src/styles/tokens.css`, then edit that file: replace the `@import "@fontsource-variable/geist"` line with

```css
@import "@fontsource/ibm-plex-sans/400.css";
@import "@fontsource/ibm-plex-sans/500.css";
@import "@fontsource/ibm-plex-sans/600.css";
@import "@fontsource/ibm-plex-mono/400.css";
```

set `--font-sans: "IBM Plex Sans", sans-serif;` and add `--font-mono: "IBM Plex Mono", monospace;` inside `@theme inline`, and replace the light `:root` colour values with the brief's palette (oklch via any converter, or sRGB hex; Tailwind 4 accepts both):

```css
:root {
  --background: #eef0f2;
  --foreground: #1c2127;
  --card: #ffffff;
  --card-foreground: #1c2127;
  --popover: #ffffff;
  --popover-foreground: #1c2127;
  --primary: #1e6e63;
  --primary-foreground: #ffffff;
  --secondary: #e4e7ea;
  --secondary-foreground: #1c2127;
  --muted: #e4e7ea;
  --muted-foreground: #5c6670;
  --accent: #e4e7ea;
  --accent-foreground: #1c2127;
  --destructive: #9a3b2e;
  --border: #d5d9de;
  --input: #d5d9de;
  --ring: #1e6e63;
  --chart-1: #1e6e63;
  --chart-2: #5c6670;
  --chart-3: #b8860b;
  --chart-4: #9a3b2e;
  --chart-5: #1c2127;
  --radius: 0.375rem;
  --status-running: #1e6e63;
  --status-ok: #d5d9de;
  --status-error: #9a3b2e;
  --status-interrupted: #b8860b;
}
```

Leave the `.dark` block as generated. Remove the `@fontsource-variable/geist` package: `npm uninstall @fontsource-variable/geist`.

`web/src/host/index.css`:

```css
@import "../styles/tokens.css";
```

`web/src/runtime/index.css`:

```css
@import "../styles/tokens.css";

/* Generated views arrive after the build, so Tailwind cannot scan them. Keep the layout
   utilities the agent reaches for available; shadcn components carry their own classes. */
@source inline("{flex,inline-flex,grid,block,hidden} {flex-col,flex-row,flex-wrap,flex-1,shrink-0,grow} {items-start,items-center,items-end,justify-start,justify-center,justify-between,justify-end}");
@source inline("{grid-cols-1,grid-cols-2,grid-cols-3,grid-cols-4} {gap-1,gap-2,gap-3,gap-4,gap-6,gap-8} {p,px,py,pt,pb,m,mx,my,mt,mb}-{0,1,2,3,4,6,8} {w,h}-full {min-h,h}-{48,64,80,96} overflow-{auto,hidden,x-auto,y-auto}");
@source inline("text-{xs,sm,base,lg,xl,2xl} font-{normal,medium,semibold} font-mono text-{left,right,center} tabular-nums truncate");
@source inline("text-{foreground,muted-foreground,primary,destructive} bg-{background,card,muted} border border-{t,b,l,r} rounded rounded-{sm,md,lg}");

html,
body,
#root {
  height: 100%;
  margin: 0;
}
```

- [ ] **Step 6: Entry HTML and minimal entries**

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Quarry</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/host/main.tsx"></script>
  </body>
</html>
```

`web/runtime.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src data:; font-src 'self'; connect-src 'none'"
    />
    <title>Quarry view</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/runtime/main.tsx"></script>
  </body>
</html>
```

`web/src/host/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";

const root = document.getElementById("root");
if (root === null) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`web/src/host/App.tsx` (placeholder until Task 10):

```tsx
export function App() {
  return <main className="p-8 text-foreground">Quarry</main>;
}
```

`web/src/runtime/main.tsx` (placeholder until Task 6):

```tsx
import "./index.css";

document.getElementById("root")?.replaceChildren("runtime");
```

Delete `web/src/App.tsx`, `web/src/main.tsx`, `web/src/index.css` from the template.

- [ ] **Step 7: Wheel artifacts**

In `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/quarry"]
artifacts = ["src/quarry/static/**"]
```

Hatchling honours `.gitignore`, so without `artifacts` the built UI would be left out of the wheel.

- [ ] **Step 8: Verify**

```bash
cd web && npm run format && npm run check && npm run build && npm test
ls ../src/quarry/static   # index.html runtime.html assets/ runtime-manifest.json
cd .. && uv build && unzip -l dist/*.whl | grep -c "quarry/static/"   # > 0
uv run pytest tests/server/test_app.py -q
```

`npm test` reports no test files; that is fine for this task. `npm run build` fails at `build:checker` until Task 3 adds `tools/transpile-check.ts`; create an empty placeholder `tools/transpile-check.ts` with `export {};` now so the script chain completes.

- [ ] **Step 9: Commit**

```bash
git add web pyproject.toml && git commit -m "build: scaffold web app with host and runtime entries"
```

---

### Task 2: Shared types, token, API client, query keys

**Files:**

- Create: `web/src/shared/json.ts`, `web/src/shared/api-types.ts`, `web/src/host/api/auth.ts`, `web/src/host/api/client.ts`, `web/src/host/api/keys.ts`
- Test: `web/src/host/api/auth.test.ts`, `web/src/host/api/client.test.ts`

**Interfaces:**

- Produces: TS mirrors of the Stage 2 pydantic models (field names as serialised: `schema`, not `schema_`); `readToken(hash)`; `ApiClient` with one method per route; `ApiError { status, detail }`; `keys.sessions()`, `keys.session(id)`, `keys.status(id)`, `keys.datasets(id)`.
- Consumes: routes and status codes from `src/quarry/server/app.py`.

- [ ] **Step 1: Types**

`web/src/shared/json.ts`:

```ts
export type Json =
  string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
```

`web/src/shared/api-types.ts`:

```ts
import type { Json, JsonObject } from "./json";

export interface Column {
  name: string;
  dtype: string;
}

export interface Filter {
  col: string;
  op:
    | "eq"
    | "ne"
    | "gt"
    | "ge"
    | "lt"
    | "le"
    | "in"
    | "not_in"
    | "contains"
    | "is_null"
    | "not_null";
  value?: Json;
}

export interface Agg {
  col: string;
  fn:
    | "sum"
    | "mean"
    | "min"
    | "max"
    | "count"
    | "median"
    | "std"
    | "first"
    | "last";
  alias?: string;
}

export interface Pivot {
  index: string[];
  columns: string;
  values: string;
  agg: Agg["fn"];
}

export interface Sort {
  col: string;
  desc?: boolean;
}

export interface QuerySpec {
  dataset: string;
  select?: string[];
  filters?: Filter[];
  group_by?: string[];
  aggs?: Agg[];
  pivot?: Pivot;
  sort?: Sort[];
  limit?: number;
  offset?: number;
  format?: "json" | "arrow";
}

export type Row = { [column: string]: Json };

export interface QueryResult {
  schema: Column[];
  rows: Row[] | null;
  arrow_base64: string | null;
  row_count: number;
  truncated: boolean;
}

export interface DatasetMeta {
  name: string;
  backing: "polars" | "duckdb";
  schema: Column[];
  rows: number | null;
  preview: Row[];
}

export interface ExecError {
  type: string;
  message: string;
  traceback: string;
}

export interface Snapshot {
  ts: string;
  state: JsonObject;
  queries: JsonObject[];
}

export interface View {
  component_id: string;
  content_hash: string;
  source: string;
  initial_state: JsonObject;
  datasets: string[];
  snapshots: Snapshot[];
}

export type StepStatus = "running" | "ok" | "error" | "interrupted";

export interface Step {
  id: string;
  index: number;
  kind: "prompt" | "manual" | "load" | "recall";
  prompt: string | null;
  code: string;
  status: StepStatus;
  error: ExecError | null;
  note: string;
  stdout_tail: string;
  stderr_tail: string;
  reads: string[];
  writes: string[];
  defines: string[];
  datasets: DatasetMeta[];
  view: View | null;
  created_at: string;
  duration_ms: number;
}

export interface SessionMeta {
  id: string;
  title: string;
  created_at: string;
  provider: { name: string; model: string };
}

export interface Session {
  meta: SessionMeta;
  steps: Step[];
}

export interface KernelStatus {
  status: "starting" | "idle" | "running" | "dead";
  pid: number | null;
}

export interface SessionStatus {
  session_id: string;
  running_step: string | null;
  kernel: KernelStatus;
  last_error: string | null;
}

export interface RepairRequest {
  step_id: string;
  error: string;
}

export interface StepRequest {
  prompt: string;
  repair?: RepairRequest;
}

export interface RestartResult {
  replayed: number;
  failed_step: Step | null;
}
```

Check the `Filter.op` and `Agg.fn` literals against `src/quarry/query/spec.py` (`FilterOp`, `AggFn`) and `RestartResult` against the `/restart` response in `service.py`; copy the exact sets.

- [ ] **Step 2: Failing tests**

`web/src/host/api/auth.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { readToken } from "./auth";

describe("readToken", () => {
  it("reads token from the fragment", () => {
    expect(readToken("#token=abc123")).toBe("abc123");
  });
  it("ignores other fragments", () => {
    expect(readToken("#foo=bar")).toBeNull();
    expect(readToken("")).toBeNull();
  });
});
```

`web/src/host/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.restoreAllMocks());

describe("ApiClient", () => {
  it("sends the bearer token", async () => {
    const fetch = fakeFetch(200, []);
    const client = new ApiClient("tok", fetch);
    await client.listSessions();
    const init = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer tok");
  });

  it("maps error responses to ApiError with the detail", async () => {
    const client = new ApiClient("tok", fakeFetch(409, { detail: "busy" }));
    await expect(client.postStep("s1", { prompt: "x" })).rejects.toMatchObject<
      Partial<ApiError>
    >({
      status: 409,
      detail: "busy",
    });
  });

  it("posts query specs as JSON", async () => {
    const fetch = fakeFetch(200, {
      schema: [],
      rows: [],
      arrow_base64: null,
      row_count: 0,
      truncated: false,
    });
    const client = new ApiClient("tok", fetch);
    await client.query("s1", { dataset: "df", limit: 5 });
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/sessions/s1/query");
    expect(init.body).toBe(JSON.stringify({ dataset: "df", limit: 5 }));
  });
});
```

Run: `cd web && npm test` — fails (modules missing).

- [ ] **Step 3: Implement**

`web/src/host/api/auth.ts`:

```ts
export function readToken(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get("token");
  return token === null || token === "" ? null : token;
}
```

`web/src/host/api/client.ts`:

```ts
import type {
  DatasetMeta,
  QueryResult,
  QuerySpec,
  RestartResult,
  Session,
  SessionMeta,
  SessionStatus,
  Step,
  StepRequest,
} from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export class ApiClient {
  constructor(
    private readonly token: string,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
  ) {}

  listSessions(): Promise<SessionMeta[]> {
    return this.request("GET", "/sessions");
  }

  createSession(title: string): Promise<SessionMeta> {
    return this.request("POST", "/sessions", { title });
  }

  getSession(id: string): Promise<Session> {
    return this.request("GET", `/sessions/${id}`);
  }

  getStatus(id: string): Promise<SessionStatus> {
    return this.request("GET", `/sessions/${id}/status`);
  }

  postStep(id: string, body: StepRequest): Promise<Step> {
    return this.request("POST", `/sessions/${id}/steps`, body);
  }

  postManualStep(id: string, code: string): Promise<Step> {
    return this.request("POST", `/sessions/${id}/steps/manual`, { code });
  }

  interrupt(id: string): Promise<{ ok: boolean }> {
    return this.request("POST", `/sessions/${id}/interrupt`);
  }

  query(id: string, spec: QuerySpec): Promise<QueryResult> {
    return this.request("POST", `/sessions/${id}/query`, spec);
  }

  datasets(id: string): Promise<DatasetMeta[]> {
    return this.request("GET", `/sessions/${id}/datasets`);
  }

  restart(id: string): Promise<RestartResult> {
    return this.request("POST", `/sessions/${id}/restart`);
  }

  postSnapshot(
    id: string,
    stepId: string,
    body: { state: JsonObject; queries: QuerySpec[] },
  ): Promise<{ count: number }> {
    return this.request(
      "POST",
      `/sessions/${id}/steps/${stepId}/snapshots`,
      body,
    );
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers = new Headers({ authorization: `Bearer ${this.token}` });
    if (body !== undefined) headers.set("content-type", "application/json");
    const response = await this.fetchImpl(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await readDetail(response);
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    return typeof data.detail === "string"
      ? data.detail
      : JSON.stringify(data.detail ?? data);
  } catch {
    return response.statusText;
  }
}
```

`web/src/host/api/keys.ts`:

```ts
export const keys = {
  sessions: () => ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  status: (id: string) => ["sessions", id, "status"] as const,
  datasets: (id: string) => ["sessions", id, "datasets"] as const,
};
```

- [ ] **Step 4: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: add typed API client and token reader"
```

---

### Task 3: Node transpile checker and runtime manifest gate

**Files:**

- Create: `web/tools/transpile-check.ts`
- Modify: `src/quarry/agent/context.py` (`runtime_libraries`, `enabled_libraries` intersection), `src/quarry/server/service.py` (`libraries` kwarg), `src/quarry/server/app.py` (pass it)
- Test: `tests/agent/test_transpile.py` (bundle test), `tests/agent/test_context.py` (gate test)

**Interfaces:**

- Produces: `static/transpile-check.mjs` reading TSX on stdin, exit 1 with the Sucrase message on stderr; `runtime_libraries(static_dir) -> list[str] | None`; `enabled_libraries(config, available=None)`; `SessionService(..., libraries=...)`.
- Consumes: `default_transpiler(static)` in `transpile.py`; `SystemContext.enabled_libraries`.

- [ ] **Step 1: Checker source**

`web/tools/transpile-check.ts`:

```ts
import { transform } from "sucrase";

const chunks: Buffer[] = [];
process.stdin.on("data", (chunk: Buffer) => chunks.push(chunk));
process.stdin.on("end", () => {
  const source = Buffer.concat(chunks).toString("utf8");
  try {
    transform(source, {
      transforms: ["typescript", "jsx", "imports"],
      jsxRuntime: "automatic",
    });
  } catch (error) {
    process.stderr.write(
      error instanceof Error ? error.message : String(error),
    );
    process.exit(1);
  }
});
```

Replace the Task 1 placeholder. `npm run build` now emits `src/quarry/static/transpile-check.mjs` (about 660 kB, Sucrase inlined).

- [ ] **Step 2: Failing Python tests**

Append to `tests/agent/test_transpile.py`:

```python
STATIC = Path(__file__).resolve().parents[2] / "src" / "quarry" / "static"


@pytest.mark.skipif(not (STATIC / "transpile-check.mjs").exists(), reason="web build missing")
def test_default_transpiler_uses_bundle() -> None:
    checker = default_transpiler(STATIC)
    assert checker.check("export default () => <div/>") is None
    problem = checker.check("const a = (")
    assert problem is not None
    assert "Unexpected token" in problem
```

Append to `tests/agent/test_context.py`:

```python
def test_runtime_libraries_reads_manifest(tmp_path: Path) -> None:
    assert runtime_libraries(tmp_path) is None
    (tmp_path / "runtime-manifest.json").write_text('{"libraries": ["ag-grid"]}')
    assert runtime_libraries(tmp_path) == ["ag-grid"]


def test_enabled_libraries_gated_by_runtime(tmp_path: Path) -> None:
    config = QuarryConfig(root=tmp_path)
    assert enabled_libraries(config, ["ag-grid", "lightweight-charts"]) == [
        "lightweight-charts",
        "ag-grid",
    ]
    assert enabled_libraries(config, None) == enabled_libraries(config)
```

Run: `uv run pytest tests/agent/test_context.py tests/agent/test_transpile.py -q` — fails on imports.

- [ ] **Step 3: Implement**

In `src/quarry/agent/context.py` add `import json` and replace `enabled_libraries`:

```python
def runtime_libraries(static_dir: Path) -> list[str] | None:
    """Library ids the built runtime bundle can resolve, or None when no build exists."""
    manifest = static_dir / "runtime-manifest.json"
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    return [str(item) for item in data.get("libraries", [])]


def enabled_libraries(config: QuarryConfig, available: list[str] | None = None) -> list[str]:
    extra: list[str] = []
    if config.libraries.highcharts_license:
        extra.append("highcharts")
    if config.libraries.scichart_license:
        extra.append("scichart")
    wanted = [*ALWAYS_ON, *extra]
    if available is None:
        return wanted
    return [lib for lib in wanted if lib in available]
```

In `service.py`, add `libraries: list[str] | None = None` to `SessionService.__init__`, store `self._libraries = libraries if libraries is not None else enabled_libraries(config)` before anything in `__init__` calls `_system_context()` (the system prompt is built there), and in `_system_context` use `enabled_libraries=self._libraries`. In `app.py`, pass `libraries=enabled_libraries(config, runtime_libraries(static))`.

- [ ] **Step 4: Verify and commit**

```bash
cd web && npm run build && cd ..
uv run pytest tests/agent -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add web/tools src tests && git commit -m "feat: gate advertised chart libraries on the built runtime"
```

---

### Task 4: Runtime loader and module table

**Files:**

- Create: `web/src/runtime/loader.ts`, `web/src/runtime/modules.ts`
- Test: `web/src/runtime/loader.test.ts`

**Interfaces:**

- Produces: `loadComponent(source, table): Promise<ViewComponent>`; `ModuleTable = Record<string, () => Promise<unknown>>`; `MODULES` (the allowlist); `ViewProps { datasets: string[] }`; `ViewComponent = ComponentType<ViewProps>`.

- [ ] **Step 1: Failing tests**

`web/src/runtime/loader.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { loadComponent, type ModuleTable } from "./loader";

const table: ModuleTable = {
  react: () => import("react").then((m) => ({ __esModule: true, ...m })),
  "react/jsx-runtime": () =>
    import("react/jsx-runtime").then((m) => ({ __esModule: true, ...m })),
  "@quarry/hooks": async () => ({
    __esModule: true,
    useQuery: () => ({ status: "loading" }),
  }),
};

describe("loadComponent", () => {
  it("transpiles TSX and returns the default export", async () => {
    const source = `
      import { useQuery } from "@quarry/hooks";
      export default function V({ datasets }: { datasets: string[] }) {
        const q = useQuery({ dataset: datasets[0] });
        return <div>{q.status}</div>;
      }`;
    const component = await loadComponent(source, table);
    expect(typeof component).toBe("function");
  });

  it("refuses imports outside the allowlist with a clear message", async () => {
    const source = `import axios from "axios"; export default () => null;`;
    await expect(loadComponent(source, table)).rejects.toThrow(
      '"axios" is not available in views',
    );
  });

  it("requires a default export", async () => {
    await expect(loadComponent(`export const x = 1;`, table)).rejects.toThrow(
      "export default",
    );
  });

  it("reports syntax errors", async () => {
    await expect(loadComponent(`const a = (`, table)).rejects.toThrow(
      /Unexpected token/,
    );
  });
});
```

- [ ] **Step 2: Implement**

`web/src/runtime/loader.ts`:

```ts
import type { ComponentType } from "react";
import { transform } from "sucrase";

export interface ViewProps {
  datasets: string[];
}

export type ViewComponent = ComponentType<ViewProps>;
export type ModuleTable = Record<string, () => Promise<unknown>>;

const REQUIRE = /require\((['"])([^'"]+)\1\)/g;

export async function loadComponent(
  source: string,
  table: ModuleTable,
): Promise<ViewComponent> {
  const { code } = transform(source, {
    transforms: ["typescript", "jsx", "imports"],
    jsxRuntime: "automatic",
    production: true,
  });
  const names = new Set([...code.matchAll(REQUIRE)].map((m) => m[2] ?? ""));
  const resolved = new Map<string, unknown>();
  for (const name of names) {
    const load = table[name];
    if (load === undefined) {
      const allowed = Object.keys(table).join(", ");
      throw new Error(
        `"${name}" is not available in views. Allowed imports: ${allowed}`,
      );
    }
    resolved.set(name, await load());
  }
  const require = (name: string): unknown => {
    if (!resolved.has(name))
      throw new Error(`"${name}" is not available in views`);
    return resolved.get(name);
  };
  const module: { exports: Record<string, unknown> } = { exports: {} };
  const factory = new Function("require", "exports", "module", code) as (
    r: typeof require,
    e: Record<string, unknown>,
    m: typeof module,
  ) => void;
  factory(require, module.exports, module);
  const component = module.exports["default"];
  if (typeof component !== "function") {
    throw new Error("the view must `export default` a React component");
  }
  return component as ViewComponent;
}
```

`web/src/runtime/modules.ts`:

```ts
import type { ModuleTable } from "./loader";

// Sucrase's interop reads `__esModule`; spreading the namespace gives it a plain object.
const esm = (ns: object): object => ({ __esModule: true, ...ns });

export const MODULES: ModuleTable = {
  react: () => import("react").then(esm),
  "react/jsx-runtime": () => import("react/jsx-runtime").then(esm),
  "@quarry/hooks": () => import("./hooks").then(esm),
  "@/components/ui/button": () => import("@/components/ui/button").then(esm),
  "@/components/ui/badge": () => import("@/components/ui/badge").then(esm),
  "@/components/ui/input": () => import("@/components/ui/input").then(esm),
  "@/components/ui/select": () => import("@/components/ui/select").then(esm),
  "@/components/ui/separator": () =>
    import("@/components/ui/separator").then(esm),
  "@/components/ui/tabs": () => import("@/components/ui/tabs").then(esm),
  "@/components/ui/tooltip": () => import("@/components/ui/tooltip").then(esm),
  "ag-grid-react": () => import("ag-grid-react").then(esm),
  "ag-grid-community": () => import("ag-grid-community").then(esm),
  "lightweight-charts": () => import("lightweight-charts").then(esm),
};
```

Vite turns each `import()` into its own chunk, so AG Grid and Lightweight Charts load only when a view imports them. `./hooks` does not exist until Task 5; create `web/src/runtime/hooks.ts` with `export {};` as a placeholder so `tsc` passes.

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: add sandboxed TSX loader with an import allowlist"
```

---

### Task 5: Runtime bridge, view state, query cache, hooks

**Files:**

- Create: `web/src/shared/bridge-types.ts`, `web/src/runtime/bridge.ts`, `web/src/runtime/state.ts`, `web/src/runtime/cache.ts`, `web/src/runtime/context.ts`, `web/src/runtime/hooks.ts`
- Test: `web/src/runtime/bridge.test.ts`, `web/src/runtime/state.test.ts`, `web/src/runtime/hooks.test.tsx`

**Interfaces:**

- Produces: `HostToRuntime` and `RuntimeToHost` unions; `RuntimeBridge` (correlation ids, `query`, `schema`, `stateChanged`, `error`, `ready`, `handle`); `ViewStateStore` (debounced `onChange`); `RequestCache`; `RuntimeContext`; hooks `useQuery`, `useViewState`, `useDatasetSchema` exactly as the spec types them.

- [ ] **Step 1: Bridge types**

`web/src/shared/bridge-types.ts`:

```ts
import type { Column, QueryResult, QuerySpec } from "./api-types";
import type { JsonObject } from "./json";

export type HostToRuntime =
  | {
      type: "mount";
      viewId: string;
      source: string;
      initialState: JsonObject;
      datasets: string[];
    }
  | { type: "restore"; viewId: string; state: JsonObject }
  | {
      type: "queryResult";
      viewId: string;
      id: string;
      ok: true;
      result: QueryResult;
    }
  | {
      type: "queryResult";
      viewId: string;
      id: string;
      ok: false;
      error: string;
    }
  | {
      type: "schemaResult";
      viewId: string;
      id: string;
      ok: true;
      schema: Column[];
    }
  | {
      type: "schemaResult";
      viewId: string;
      id: string;
      ok: false;
      error: string;
    };

export type RuntimeToHost =
  | { type: "ready" }
  | { type: "query"; viewId: string; id: string; spec: QuerySpec }
  | { type: "schema"; viewId: string; id: string; dataset: string }
  | {
      type: "stateChanged";
      viewId: string;
      state: JsonObject;
      queries: QuerySpec[];
    }
  | { type: "error"; viewId: string; message: string; stack?: string };

export function isRuntimeMessage(data: unknown): data is RuntimeToHost {
  return typeof data === "object" && data !== null && "type" in data;
}

export function isHostMessage(data: unknown): data is HostToRuntime {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    "viewId" in data
  );
}
```

`queryResult` carries the server's `QueryResult` verbatim (`schema`, `rows`, `arrow_base64`, `row_count`, `truncated`) rather than re-flattening it; the host already holds that object.

- [ ] **Step 2: Failing tests**

`web/src/runtime/bridge.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";

function setup() {
  const sent: RuntimeToHost[] = [];
  const bridge = new RuntimeBridge("v1", (m) => sent.push(m));
  return { bridge, sent };
}

describe("RuntimeBridge", () => {
  it("resolves a query with the matching id", async () => {
    const { bridge, sent } = setup();
    const promise = bridge.query({ dataset: "df" });
    const msg = sent[0];
    if (msg?.type !== "query") throw new Error("expected query");
    bridge.handle({
      type: "queryResult",
      viewId: "v1",
      id: msg.id,
      ok: true,
      result: {
        schema: [],
        rows: [],
        arrow_base64: null,
        row_count: 0,
        truncated: false,
      },
    });
    await expect(promise).resolves.toMatchObject({ row_count: 0 });
  });

  it("rejects on error results and ignores foreign ids", async () => {
    const { bridge, sent } = setup();
    const promise = bridge.query({ dataset: "df" });
    bridge.handle({
      type: "queryResult",
      viewId: "v1",
      id: "nope",
      ok: false,
      error: "x",
    });
    const msg = sent[0];
    if (msg?.type !== "query") throw new Error("expected query");
    bridge.handle({
      type: "queryResult",
      viewId: "v1",
      id: msg.id,
      ok: false,
      error: "bad",
    });
    await expect(promise).rejects.toThrow("bad");
  });

  it("stateChanged carries the specs issued since the last change", () => {
    const { bridge, sent } = setup();
    void bridge.query({ dataset: "a" });
    bridge.stateChanged({ k: 1 });
    void bridge.query({ dataset: "b" });
    bridge.stateChanged({ k: 2 });
    const changes = sent.filter((m) => m.type === "stateChanged");
    expect(
      changes.map((m) => (m.type === "stateChanged" ? m.queries : [])),
    ).toEqual([[{ dataset: "a" }], [{ dataset: "b" }]]);
  });

  it("ignores messages for other views", () => {
    const { bridge } = setup();
    const spy = vi.fn();
    bridge.handle({ type: "restore", viewId: "other", state: {} }, spy);
    expect(spy).not.toHaveBeenCalled();
  });
});
```

`web/src/runtime/state.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { ViewStateStore } from "./state";

describe("ViewStateStore", () => {
  it("debounces onChange and reports the whole state", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const store = new ViewStateStore({ a: 1 }, onChange, 300);
    store.set("b", 2);
    store.set("b", 3);
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ a: 1, b: 3 });
    vi.useRealTimers();
  });

  it("replace notifies subscribers without reporting a change", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore({}, onChange, 0);
    const listener = vi.fn();
    store.subscribe(listener);
    store.replace({ x: "y" });
    expect(listener).toHaveBeenCalled();
    expect(store.get("x")).toBe("y");
    expect(onChange).not.toHaveBeenCalled();
  });
});
```

`web/src/runtime/hooks.test.tsx`:

```tsx
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";
import { RequestCache } from "./cache";
import { RuntimeProvider } from "./context";
import { useDatasetSchema, useQuery, useViewState } from "./hooks";
import { ViewStateStore } from "./state";

function harness() {
  const sent: RuntimeToHost[] = [];
  const bridge = new RuntimeBridge("v1", (m) => sent.push(m));
  const store = new ViewStateStore({ limit: 10 }, () => undefined, 0);
  const cache = new RequestCache(bridge);
  const wrap = (ui: React.ReactNode) => (
    <RuntimeProvider value={{ bridge, store, cache }}>{ui}</RuntimeProvider>
  );
  return { bridge, store, cache, sent, wrap };
}

function Probe() {
  const [limit, setLimit] = useViewState<number>("limit", 5);
  const q = useQuery({ dataset: "df", limit });
  const schema = useDatasetSchema("df");
  return (
    <div>
      <span data-testid="status">{q.status}</span>
      <span data-testid="limit">{limit}</span>
      <span data-testid="schema">
        {schema === null ? "none" : schema.length}
      </span>
      <button onClick={() => setLimit(limit + 1)}>more</button>
    </div>
  );
}

describe("hooks", () => {
  it("useQuery goes loading -> success and dedupes identical specs", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<Probe />));
    expect(screen.getByTestId("status").textContent).toBe("loading");
    const queries = sent.filter((m) => m.type === "query");
    expect(queries).toHaveLength(1);
    const msg = queries[0];
    if (msg?.type !== "query") throw new Error("expected query");
    await act(async () => {
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        result: {
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: 0,
          truncated: false,
        },
      });
    });
    expect(screen.getByTestId("status").textContent).toBe("success");
  });

  it("useViewState reads the mounted state and re-queries on change", async () => {
    const { sent, wrap } = harness();
    render(wrap(<Probe />));
    expect(screen.getByTestId("limit").textContent).toBe("10");
    await act(async () => {
      screen.getByText("more").click();
    });
    expect(screen.getByTestId("limit").textContent).toBe("11");
    const specs = sent
      .filter((m) => m.type === "query")
      .map((m) => (m.type === "query" ? m.spec : null));
    expect(specs).toEqual([
      { dataset: "df", limit: 10 },
      { dataset: "df", limit: 11 },
    ]);
  });

  it("useDatasetSchema resolves through the bridge", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<Probe />));
    const msg = sent.find((m) => m.type === "schema");
    if (msg?.type !== "schema") throw new Error("expected schema request");
    await act(async () => {
      bridge.handle({
        type: "schemaResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        schema: [{ name: "a", dtype: "Int64" }],
      });
    });
    expect(screen.getByTestId("schema").textContent).toBe("1");
  });
});
```

- [ ] **Step 3: Implement**

`web/src/runtime/bridge.ts`:

```ts
import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import type { HostToRuntime, RuntimeToHost } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

export class RuntimeBridge {
  private readonly pending = new Map<string, Pending>();
  private issued: QuerySpec[] = [];
  private counter = 0;

  constructor(
    readonly viewId: string,
    private readonly post: (message: RuntimeToHost) => void,
  ) {}

  ready(): void {
    this.post({ type: "ready" });
  }

  query(spec: QuerySpec): Promise<QueryResult> {
    this.issued.push(spec);
    const id = this.nextId();
    this.post({ type: "query", viewId: this.viewId, id, spec });
    return this.wait<QueryResult>(id);
  }

  schema(dataset: string): Promise<Column[]> {
    const id = this.nextId();
    this.post({ type: "schema", viewId: this.viewId, id, dataset });
    return this.wait<Column[]>(id);
  }

  stateChanged(state: JsonObject): void {
    const queries = this.issued;
    this.issued = [];
    this.post({ type: "stateChanged", viewId: this.viewId, state, queries });
  }

  error(message: string, stack?: string): void {
    this.post({ type: "error", viewId: this.viewId, message, stack });
  }

  /** Routes a host message; `onControl` receives mount and restore. */
  handle(message: HostToRuntime, onControl?: (m: HostToRuntime) => void): void {
    if (message.viewId !== this.viewId) return;
    if (message.type === "queryResult" || message.type === "schemaResult") {
      const pending = this.pending.get(message.id);
      if (pending === undefined) return;
      this.pending.delete(message.id);
      if (message.ok)
        pending.resolve(
          message.type === "queryResult" ? message.result : message.schema,
        );
      else pending.reject(new Error(message.error));
      return;
    }
    onControl?.(message);
  }

  private nextId(): string {
    this.counter += 1;
    return `${this.viewId}:${this.counter}`;
  }

  private wait<T>(id: string): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: (v) => resolve(v as T), reject });
    });
  }
}
```

`web/src/runtime/state.ts`:

```ts
import type { Json, JsonObject } from "@/shared/json";

export class ViewStateStore {
  private values: Map<string, Json>;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private cached: JsonObject;

  constructor(
    initial: JsonObject,
    private readonly onChange: (state: JsonObject) => void,
    private readonly debounceMs: number,
  ) {
    this.values = new Map(Object.entries(initial));
    this.cached = { ...initial };
  }

  get(key: string): Json | undefined {
    return this.values.get(key);
  }

  set(key: string, value: Json): void {
    this.values.set(key, value);
    this.cached = this.snapshot();
    this.notify();
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.onChange(this.cached);
    }, this.debounceMs);
  }

  replace(state: JsonObject): void {
    this.values = new Map(Object.entries(state));
    this.cached = { ...state };
    this.notify();
  }

  /** Stable reference between changes, for useSyncExternalStore. */
  current(): JsonObject {
    return this.cached;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private snapshot(): JsonObject {
    return Object.fromEntries(this.values);
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
```

`web/src/runtime/cache.ts`:

```ts
import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import type { RuntimeBridge } from "./bridge";

export type QueryState =
  | { status: "loading" }
  | { status: "success"; result: QueryResult }
  | { status: "error"; message: string };

export type SchemaState =
  { status: "loading" } | { status: "done"; schema: Column[] | null };

const LOADING: QueryState = { status: "loading" };
const SCHEMA_LOADING: SchemaState = { status: "loading" };

/** Idempotent per-view request cache; `ensure*` may be called during render. */
export class RequestCache {
  private readonly queries = new Map<string, QueryState>();
  private readonly schemas = new Map<string, SchemaState>();
  private readonly listeners = new Set<() => void>();

  constructor(private readonly bridge: RuntimeBridge) {}

  ensureQuery(spec: QuerySpec): QueryState {
    const key = JSON.stringify(spec);
    const known = this.queries.get(key);
    if (known !== undefined) return known;
    this.queries.set(key, LOADING);
    this.bridge.query(spec).then(
      (result) => this.put(this.queries, key, { status: "success", result }),
      (error: unknown) =>
        this.put(this.queries, key, {
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        }),
    );
    return LOADING;
  }

  ensureSchema(dataset: string): SchemaState {
    const known = this.schemas.get(dataset);
    if (known !== undefined) return known;
    this.schemas.set(dataset, SCHEMA_LOADING);
    this.bridge.schema(dataset).then(
      (schema) => this.put(this.schemas, dataset, { status: "done", schema }),
      () => this.put(this.schemas, dataset, { status: "done", schema: null }),
    );
    return SCHEMA_LOADING;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private put<T>(map: Map<string, T>, key: string, value: T): void {
    map.set(key, value);
    for (const listener of this.listeners) listener();
  }
}
```

`web/src/runtime/context.ts`:

```ts
import { createContext, useContext } from "react";
import type { RuntimeBridge } from "./bridge";
import type { RequestCache } from "./cache";
import type { ViewStateStore } from "./state";

export interface RuntimeServices {
  bridge: RuntimeBridge;
  store: ViewStateStore;
  cache: RequestCache;
}

const RuntimeContext = createContext<RuntimeServices | null>(null);

export const RuntimeProvider = RuntimeContext.Provider;

export function useRuntime(): RuntimeServices {
  const services = useContext(RuntimeContext);
  if (services === null)
    throw new Error("hooks from @quarry/hooks only work inside a view");
  return services;
}
```

`web/src/runtime/hooks.ts` (replace the placeholder):

```ts
import { useCallback, useSyncExternalStore } from "react";
import type { Column, QuerySpec, Row } from "@/shared/api-types";
import type { Json } from "@/shared/json";
import { useRuntime } from "./context";

export type QueryHookResult =
  | { status: "loading" }
  | {
      status: "success";
      rows: Row[];
      schema: Column[];
      rowCount: number;
      truncated: boolean;
    }
  | { status: "error"; message: string };

export function useQuery(spec: QuerySpec): QueryHookResult {
  const { cache } = useRuntime();
  const key = JSON.stringify(spec);
  const state = useSyncExternalStore(cache.subscribe.bind(cache), () =>
    cache.ensureQuery(JSON.parse(key) as QuerySpec),
  );
  if (state.status === "success") {
    const { result } = state;
    return {
      status: "success",
      rows: result.rows ?? [],
      schema: result.schema,
      rowCount: result.row_count,
      truncated: result.truncated,
    };
  }
  return state;
}

export function useViewState<T extends Json>(
  key: string,
  initial: T,
): [T, (next: T) => void] {
  const { store } = useRuntime();
  const state = useSyncExternalStore(store.subscribe.bind(store), () =>
    store.current(),
  );
  const value = key in state ? (state[key] as T) : initial;
  const set = useCallback((next: T) => store.set(key, next), [store, key]);
  return [value, set];
}

export function useDatasetSchema(name: string): Column[] | null {
  const { cache } = useRuntime();
  const state = useSyncExternalStore(cache.subscribe.bind(cache), () =>
    cache.ensureSchema(name),
  );
  return state.status === "done" ? state.schema : null;
}
```

The success shape adds `rowCount` and `truncated` to the spec's `{ rows, schema }`; built-ins need them for the truncation banner. Add the two fields to the `CONTRACT` hook line in `src/quarry/agent/context.py` in Task 8.

- [ ] **Step 4: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: add runtime bridge, view state store and hooks"
```

---

### Task 6: Runtime entry: mount, restore, error boundary

**Files:**

- Create: `web/src/runtime/ErrorBoundary.tsx`, `web/src/runtime/mount.tsx`
- Modify: `web/src/runtime/main.tsx`
- Test: `web/src/runtime/mount.test.tsx`

**Interfaces:**

- Produces: `createRuntime(post, root)` returning `{ handle(message) }`; renders `<Component datasets={…} />` inside `RuntimeProvider` and `ErrorBoundary`; posts `ready` once, `error` on load or render failure.

- [ ] **Step 1: Failing test**

`web/src/runtime/mount.test.tsx`:

```tsx
import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { createRuntime } from "./mount";

const table = {
  react: () => import("react").then((m) => ({ __esModule: true, ...m })),
  "react/jsx-runtime": () =>
    import("react/jsx-runtime").then((m) => ({ __esModule: true, ...m })),
  "@quarry/hooks": () =>
    import("./hooks").then((m) => ({ __esModule: true, ...m })),
};

function setup() {
  const sent: RuntimeToHost[] = [];
  const root = document.createElement("div");
  document.body.appendChild(root);
  const runtime = createRuntime((m) => sent.push(m), root, table);
  return { runtime, sent };
}

describe("runtime mount", () => {
  it("posts ready, mounts a component with datasets, and restores state", async () => {
    const { runtime, sent } = setup();
    expect(sent[0]).toEqual({ type: "ready" });
    const source = `
      import { useViewState } from "@quarry/hooks";
      export default function V({ datasets }) {
        const [n] = useViewState("n", 0);
        return <p>{datasets.join(",")}:{n}</p>;
      }`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v1",
        source,
        initialState: { n: 1 },
        datasets: ["df"],
      });
    });
    await waitFor(() => expect(screen.getByText("df:1")).toBeTruthy());
    await act(async () => {
      runtime.handle({ type: "restore", viewId: "v1", state: { n: 7 } });
    });
    await waitFor(() => expect(screen.getByText("df:7")).toBeTruthy());
  });

  it("posts error when the component throws during render", async () => {
    const { runtime, sent } = setup();
    const source = `export default function V() { throw new Error("boom"); }`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v2",
        source,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(
        sent.some((m) => m.type === "error" && m.message.includes("boom")),
      ).toBe(true),
    );
  });

  it("posts error when an import is refused", async () => {
    const { runtime, sent } = setup();
    const source = `import d3 from "d3"; export default () => null;`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v3",
        source,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(
        sent.some(
          (m) => m.type === "error" && m.message.includes("not available"),
        ),
      ).toBe(true),
    );
  });
});
```

- [ ] **Step 2: Implement**

`web/src/runtime/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  onError: (error: Error) => void;
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
  resetKey: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: Props,
    state: State,
  ): Partial<State> | null {
    return props.resetKey === state.resetKey
      ? null
      : { error: null, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    this.props.onError(error);
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <pre className="m-4 whitespace-pre-wrap font-mono text-sm text-destructive">
          {this.state.error.message}
        </pre>
      );
    }
    return this.props.children;
  }
}
```

`web/src/runtime/mount.tsx`:

```tsx
import { createRoot, type Root } from "react-dom/client";
import type { HostToRuntime, RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";
import { RequestCache } from "./cache";
import { RuntimeProvider } from "./context";
import { ErrorBoundary } from "./ErrorBoundary";
import { loadComponent, type ModuleTable, type ViewComponent } from "./loader";
import { MODULES } from "./modules";
import { ViewStateStore } from "./state";

export interface Runtime {
  handle(message: HostToRuntime): void;
}

interface Mounted {
  bridge: RuntimeBridge;
  store: ViewStateStore;
}

export function createRuntime(
  post: (message: RuntimeToHost) => void,
  container: HTMLElement,
  table: ModuleTable = MODULES,
): Runtime {
  const root: Root = createRoot(container);
  let mounted: Mounted | null = null;

  const render = (
    m: Mounted,
    cache: RequestCache,
    component: ViewComponent,
    datasets: string[],
  ) => {
    root.render(
      <RuntimeProvider value={{ bridge: m.bridge, store: m.store, cache }}>
        <ErrorBoundary
          resetKey={m.bridge.viewId}
          onError={(e) => m.bridge.error(e.message, e.stack)}
        >
          <View component={component} datasets={datasets} />
        </ErrorBoundary>
      </RuntimeProvider>,
    );
  };

  const mount = async (message: Extract<HostToRuntime, { type: "mount" }>) => {
    const bridge = new RuntimeBridge(message.viewId, post);
    const store = new ViewStateStore(
      message.initialState,
      (s) => bridge.stateChanged(s),
      300,
    );
    const cache = new RequestCache(bridge);
    mounted = { bridge, store };
    try {
      const component = await loadComponent(message.source, table);
      render(mounted, cache, component, message.datasets);
    } catch (error) {
      const e = error instanceof Error ? error : new Error(String(error));
      bridge.error(e.message, e.stack);
      root.render(
        <pre className="m-4 whitespace-pre-wrap font-mono text-sm text-destructive">
          {e.message}
        </pre>,
      );
    }
  };

  post({ type: "ready" });

  return {
    handle(message) {
      if (message.type === "mount") {
        void mount(message);
        return;
      }
      if (mounted === null) return;
      mounted.bridge.handle(message, (control) => {
        if (control.type === "restore") mounted?.store.replace(control.state);
      });
    },
  };
}

function View({
  component: Component,
  datasets,
}: {
  component: ViewComponent;
  datasets: string[];
}) {
  return <Component datasets={datasets} />;
}
```

`web/src/runtime/main.tsx`:

```tsx
import { isHostMessage } from "@/shared/bridge-types";
import { createRuntime } from "./mount";
import "./index.css";

const root = document.getElementById("root");
if (root === null) throw new Error("missing #root");

const runtime = createRuntime(
  (message) => window.parent.postMessage(message, "*"),
  root,
);

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window.parent) return;
  if (!isHostMessage(event.data)) return;
  runtime.handle(event.data);
});
```

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build
git add web && git commit -m "feat: mount generated views in the iframe runtime"
```

---

### Task 7: Host bridge and view frame

**Files:**

- Create: `web/src/host/bridge/HostBridge.ts`, `web/src/host/components/ViewFrame.tsx`
- Test: `web/src/host/bridge/HostBridge.test.ts`

**Interfaces:**

- Produces: `HostBridge` with `listen(window): () => void`, `mount(view)`, `restore(state)`; options `{ viewId, frame: { postMessage }, isFrame(source), onQuery, onSchema, onStateChanged, onError }`; `ViewFrame` presentational component owning the `<iframe sandbox="allow-scripts" src="/runtime.html">` and an error overlay.

- [ ] **Step 1: Failing test**

`web/src/host/bridge/HostBridge.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import type { HostToRuntime } from "@/shared/bridge-types";
import { HostBridge } from "./HostBridge";

function setup() {
  const posted: HostToRuntime[] = [];
  const frameWindow = { postMessage: (m: HostToRuntime) => posted.push(m) };
  const onQuery = vi.fn(async () => ({
    schema: [],
    rows: [{ a: 1 }],
    arrow_base64: null,
    row_count: 1,
    truncated: false,
  }));
  const onStateChanged = vi.fn();
  const onError = vi.fn();
  const bridge = new HostBridge({
    viewId: "v1",
    frame: frameWindow,
    isFrame: (source) => source === frameWindow,
    onQuery,
    onSchema: async () => [],
    onStateChanged,
    onError,
  });
  // jsdom rejects a plain object as MessageEvent.source, so tests feed handleEvent directly.
  const send = (data: unknown, source: unknown = frameWindow) =>
    bridge.handleEvent({ data, source });
  return { bridge, posted, send, onQuery, onStateChanged, onError };
}

describe("HostBridge", () => {
  it("mounts after ready and answers queries", async () => {
    const { bridge, posted, send, onQuery } = setup();
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"] });
    expect(posted).toHaveLength(0);
    send({ type: "ready" });
    expect(posted[0]).toMatchObject({
      type: "mount",
      viewId: "v1",
      datasets: ["df"],
    });
    send({ type: "query", viewId: "v1", id: "q1", spec: { dataset: "df" } });
    await vi.waitFor(() => expect(posted).toHaveLength(2));
    expect(onQuery).toHaveBeenCalledWith({ dataset: "df" });
    expect(posted[1]).toMatchObject({
      type: "queryResult",
      id: "q1",
      ok: true,
    });
  });

  it("ignores messages from other sources", () => {
    const { posted, send, onStateChanged } = setup();
    send(
      { type: "stateChanged", viewId: "v1", state: {}, queries: [] },
      window,
    );
    expect(onStateChanged).not.toHaveBeenCalled();
    expect(posted).toHaveLength(0);
  });

  it("forwards stateChanged and error", () => {
    const { send, onStateChanged, onError } = setup();
    send({
      type: "stateChanged",
      viewId: "v1",
      state: { k: 1 },
      queries: [{ dataset: "df" }],
    });
    expect(onStateChanged).toHaveBeenCalledWith({ k: 1 }, [{ dataset: "df" }]);
    send({ type: "error", viewId: "v1", message: "boom" });
    expect(onError).toHaveBeenCalledWith("boom", undefined);
  });

  it("reports query failures as error results", async () => {
    const posted: HostToRuntime[] = [];
    const failing = new HostBridge({
      viewId: "v2",
      frame: { postMessage: (m) => posted.push(m) },
      isFrame: () => true,
      onQuery: async () => {
        throw new Error("400: bad spec");
      },
      onSchema: async () => [],
      onStateChanged: () => undefined,
      onError: () => undefined,
    });
    failing.handleEvent({
      data: { type: "query", viewId: "v2", id: "q9", spec: { dataset: "df" } },
      source: null,
    });
    await vi.waitFor(() =>
      expect(posted.at(-1)).toMatchObject({
        type: "queryResult",
        id: "q9",
        ok: false,
        error: "400: bad spec",
      }),
    );
  });

  it("listen wires window messages through handleEvent", () => {
    const { bridge } = setup();
    const spy = vi.spyOn(bridge, "handleEvent");
    const stop = bridge.listen(window);
    window.dispatchEvent(
      new MessageEvent("message", { data: { type: "ready" } }),
    );
    expect(spy).toHaveBeenCalled();
    stop();
  });
});
```

- [ ] **Step 2: Implement**

`web/src/host/bridge/HostBridge.ts`:

```ts
import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import {
  isRuntimeMessage,
  type HostToRuntime,
  type RuntimeToHost,
} from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";

export interface MountSpec {
  source: string;
  initialState: JsonObject;
  datasets: string[];
}

export interface HostBridgeOptions {
  viewId: string;
  frame: { postMessage(message: HostToRuntime, targetOrigin: string): void };
  isFrame: (source: unknown) => boolean;
  onQuery: (spec: QuerySpec) => Promise<QueryResult>;
  onSchema: (dataset: string) => Promise<Column[]>;
  onStateChanged: (state: JsonObject, queries: QuerySpec[]) => void;
  onError: (message: string, stack?: string) => void;
}

export class HostBridge {
  private ready = false;
  private pendingMount: MountSpec | null = null;

  constructor(private readonly options: HostBridgeOptions) {}

  listen(target: Window): () => void {
    const handler = (event: MessageEvent<unknown>) => this.handleEvent(event);
    target.addEventListener("message", handler);
    return () => target.removeEventListener("message", handler);
  }

  handleEvent(event: { data: unknown; source: unknown }): void {
    if (!this.options.isFrame(event.source)) return;
    if (!isRuntimeMessage(event.data)) return;
    this.receive(event.data);
  }

  mount(spec: MountSpec): void {
    this.pendingMount = spec;
    if (this.ready) this.flushMount();
  }

  restore(state: JsonObject): void {
    this.send({ type: "restore", viewId: this.options.viewId, state });
  }

  private receive(message: RuntimeToHost): void {
    if (message.type === "ready") {
      this.ready = true;
      this.flushMount();
      return;
    }
    if (message.viewId !== this.options.viewId) return;
    const { viewId } = this.options;
    switch (message.type) {
      case "query":
        void this.options.onQuery(message.spec).then(
          (result) =>
            this.send({
              type: "queryResult",
              viewId,
              id: message.id,
              ok: true,
              result,
            }),
          (error: unknown) =>
            this.send({
              type: "queryResult",
              viewId,
              id: message.id,
              ok: false,
              error: text(error),
            }),
        );
        return;
      case "schema":
        void this.options.onSchema(message.dataset).then(
          (schema) =>
            this.send({
              type: "schemaResult",
              viewId,
              id: message.id,
              ok: true,
              schema,
            }),
          (error: unknown) =>
            this.send({
              type: "schemaResult",
              viewId,
              id: message.id,
              ok: false,
              error: text(error),
            }),
        );
        return;
      case "stateChanged":
        this.options.onStateChanged(message.state, message.queries);
        return;
      case "error":
        this.options.onError(message.message, message.stack);
        return;
    }
  }

  private flushMount(): void {
    if (this.pendingMount === null) return;
    const { source, initialState, datasets } = this.pendingMount;
    this.pendingMount = null;
    this.send({
      type: "mount",
      viewId: this.options.viewId,
      source,
      initialState,
      datasets,
    });
  }

  private send(message: HostToRuntime): void {
    // The sandboxed frame has an opaque origin; "*" is the only target that reaches it.
    this.options.frame.postMessage(message, "*");
  }
}

function text(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
```

`web/src/host/components/ViewFrame.tsx` (presentational; the container in Task 11 wires the bridge):

```tsx
import { forwardRef } from "react";
import { Button } from "@/components/ui/button";

interface ViewFrameProps {
  title: string;
  error: string | null;
  onFix: () => void;
}

export const ViewFrame = forwardRef<HTMLIFrameElement, ViewFrameProps>(
  function ViewFrame({ title, error, onFix }, ref) {
    return (
      <div className="relative border-y border-border bg-card">
        <iframe
          ref={ref}
          title={title}
          src="/runtime.html"
          sandbox="allow-scripts"
          className="block h-[420px] w-full"
        />
        {error !== null && (
          <div className="absolute inset-0 flex flex-col gap-3 overflow-auto bg-card p-4">
            <p className="text-sm text-muted-foreground">
              The view did not mount.
            </p>
            <pre className="whitespace-pre-wrap font-mono text-sm text-destructive">
              {error}
            </pre>
            <div>
              <Button size="sm" onClick={onFix}>
                Fix this view
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  },
);
```

React 19 accepts `ref` as a plain prop; `forwardRef` is still fine and keeps the type explicit. Either is acceptable.

The `ready` handshake has a narrow race: the host attaches its listener in an effect after the iframe element exists, and the runtime posts `ready` when its module script runs. The effect wins in practice because the iframe document has not loaded yet. If the Playwright test ever flakes on mount, add a `load` listener on the iframe that calls a public `flushMount()` on the bridge; module scripts run before `load`, so by then `ready` has been sent and a second `mount` is harmless.

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: add host side of the view bridge"
```

---

### Task 8: Built-in components: data table and time series

**Files:**

- Create: `src/quarry/components/builtin/data-table/manifest.json`, `src/quarry/components/builtin/data-table/component.tsx`, `src/quarry/components/builtin/time-series/manifest.json`, `src/quarry/components/builtin/time-series/component.tsx`
- Modify: `src/quarry/agent/context.py` (`CONTRACT`: the `datasets` prop and the success fields)
- Test: `web/src/builtins/data-table.test.tsx`, `web/src/builtins/time-series.test.tsx`, `tests/components/test_builtin.py`, `tests/agent/test_context.py` (one assertion)

**Interfaces:**

- Produces: two library entries with ids `data-table` and `time-series`; both read `datasets[0]`, push state through `useViewState`, and build query specs from it.
- Consumes: `ComponentLibrary` scanning `builtin_root()`; `useQuery`, `useViewState`, `useDatasetSchema` from Task 5.

- [ ] **Step 1: Manifests**

`src/quarry/components/builtin/data-table/manifest.json`:

```json
{
  "id": "data-table",
  "name": "Data table",
  "description": "Sortable, filterable grid over one dataset. Columns come from the schema.",
  "tags": ["table", "grid", "rows", "inspect"],
  "contract_version": 1,
  "schema": { "requires": [] },
  "origin": "builtin",
  "created_at": "2026-10-08T00:00:00Z"
}
```

`src/quarry/components/builtin/time-series/manifest.json`:

```json
{
  "id": "time-series",
  "name": "Time series",
  "description": "Line chart of one numeric column over a date or datetime column.",
  "tags": ["line", "time", "series", "price", "returns"],
  "contract_version": 1,
  "schema": {
    "requires": [
      { "role": "time", "dtype": "datetime", "min": 1 },
      { "role": "value", "dtype": "numeric", "min": 1 }
    ]
  },
  "origin": "builtin",
  "created_at": "2026-10-08T00:00:00Z"
}
```

Check the `requires` item field names against `ComponentSchema` in `library.py` and the existing `tests/components/test_library.py` fixtures; match them exactly.

- [ ] **Step 2: Failing tests**

`web/src/builtins/data-table.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => null,
}));
// The grid itself is AG Grid's to test; jsdom has no layout, so stub it and check the contract.
vi.mock("ag-grid-react", () => ({
  AgGridReact: () => <div data-testid="grid" />,
}));
vi.mock("ag-grid-community", () => ({
  AllCommunityModule: {},
  ModuleRegistry: { registerModules: () => undefined },
  themeQuartz: { withParams: () => ({}) },
}));

import DataTable from "@builtin/data-table/component";

describe("data-table built-in", () => {
  it("queries the first dataset with a limit and renders a truncation banner", () => {
    query.mockReturnValue({
      status: "success",
      rows: [{ a: 1 }],
      schema: [{ name: "a", dtype: "Int64" }],
      rowCount: 50000,
      truncated: true,
    });
    render(<DataTable datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: "df", limit: 1000 }),
    );
    expect(screen.getByText(/showing 1 of 50,000 rows/i)).toBeTruthy();
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<DataTable datasets={["df"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
```

`web/src/builtins/time-series.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => [
    { name: "ts", dtype: "Date" },
    { name: "px", dtype: "Float64" },
  ],
}));
vi.mock("lightweight-charts", () => ({
  LineSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    applyOptions: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

import TimeSeries from "@builtin/time-series/component";

describe("time-series built-in", () => {
  it("picks the first datetime and numeric columns and sorts by time", () => {
    query.mockReturnValue({ status: "loading" });
    render(<TimeSeries datasets={["px"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "px",
      select: ["ts", "px"],
      sort: [{ col: "ts" }],
      limit: 50000,
    });
    expect(screen.getByText("Loading")).toBeTruthy();
  });
});
```

`tests/components/test_builtin.py`:

```python
from quarry.components.library import ComponentLibrary, builtin_root


def test_builtin_library_lists_stage3_components() -> None:
    library = ComponentLibrary([builtin_root()])
    ids = {entry.manifest.id for entry in library.entries()}
    assert {"data-table", "time-series"} <= ids
    table = library.get("data-table")
    assert table is not None
    assert "export default" in table.source_path.read_text()
```

Check the library's listing method name (`entries()`, `list()`, or similar) in `library.py` and use that.

Add to `tests/agent/test_context.py`'s `test_build_system_is_deterministic_and_filtered`:

```python
    assert "datasets: string[]" in system
```

- [ ] **Step 3: Implement the table**

`src/quarry/components/builtin/data-table/component.tsx`:

```tsx
import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type SortChangedEvent,
} from "ag-grid-community";
import { useQuery, useViewState } from "@quarry/hooks";

ModuleRegistry.registerModules([AllCommunityModule]);

interface Props {
  datasets: string[];
}

interface SortState {
  col: string;
  desc: boolean;
}

const theme = themeQuartz.withParams({
  fontFamily: "IBM Plex Sans, sans-serif",
  cellFontFamily: "IBM Plex Mono, monospace",
  fontSize: 13,
  rowHeight: 28,
  headerHeight: 30,
});

export default function DataTable({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const [sort, setSort] = useViewState<SortState | null>("sort", null);
  const [limit] = useViewState<number>("limit", 1000);
  const result = useQuery({
    dataset,
    limit,
    ...(sort === null ? {} : { sort: [{ col: sort.col, desc: sort.desc }] }),
  });

  const columnDefs = useMemo<ColDef[]>(() => {
    if (result.status !== "success") return [];
    return result.schema.map((column) => ({
      field: column.name,
      headerName: column.name,
      sortable: true,
      resizable: true,
      filter: true,
      sort: sort?.col === column.name ? (sort.desc ? "desc" : "asc") : null,
      type: /^(Int|UInt|Float|Decimal)/.test(column.dtype)
        ? "numericColumn"
        : undefined,
    }));
  }, [result, sort]);

  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const onSortChanged = (event: SortChangedEvent) => {
    const sorted = event.api
      .getColumnState()
      .find((c) => c.sort !== null && c.sort !== undefined);
    setSort(
      sorted?.colId === undefined
        ? null
        : { col: sorted.colId, desc: sorted.sort === "desc" },
    );
  };

  return (
    <div className="flex h-full flex-col">
      {result.truncated && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing {result.rows.length.toLocaleString()} of{" "}
          {result.rowCount.toLocaleString()} rows. Sort or filter to narrow the
          data.
        </p>
      )}
      <div className="min-h-0 flex-1">
        <AgGridReact
          theme={theme}
          rowData={result.rows}
          columnDefs={columnDefs}
          onSortChanged={onSortChanged}
          suppressMultiSort
        />
      </div>
    </div>
  );
}
```

Sorting is pushed into the query spec, so the server sorts the full dataset and the grid shows the top `limit` rows. The `filter: true` column filters stay client side in Stage 3; moving them into `filters` is a Stage 5 refinement.

- [ ] **Step 4: Implement the time series**

`src/quarry/components/builtin/time-series/component.tsx`:

```tsx
import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

interface Columns {
  time: string | null;
  value: string | null;
}

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function TimeSeries({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    time: null,
    value: null,
  });
  const time =
    chosen.time ?? schema?.find((c) => isTime(c.dtype))?.name ?? null;
  const value =
    chosen.value ?? schema?.find((c) => isNumeric(c.dtype))?.name ?? null;
  const ready = time !== null && value !== null;
  const result = useQuery(
    ready
      ? { dataset, select: [time, value], sort: [{ col: time }], limit: 50000 }
      : { dataset, limit: 1 },
  );
  const container = useRef<HTMLDivElement>(null);

  // Lightweight Charts owns its canvas; this is the one place a DOM library needs an effect.
  useEffect(() => {
    const el = container.current;
    if (el === null || !ready || result.status !== "success") return;
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        fontFamily: "IBM Plex Sans, sans-serif",
      },
    });
    const series = chart.addSeries(LineSeries, {
      color: "#1e6e63",
      lineWidth: 2,
    });
    series.setData(result.rows.map((row) => point(row, time, value)));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [ready, result, time, value]);

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and a numeric column.
      </p>
    );
  }
  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-3 border-b border-border px-3 py-1 text-sm">
        <ColumnPicker
          label="Time"
          value={time}
          options={schema.filter((c) => isTime(c.dtype)).map((c) => c.name)}
          onChange={(t) => setChosen({ time: t, value })}
        />
        <ColumnPicker
          label="Value"
          value={value}
          options={schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ time, value: v })}
        />
      </div>
      <div ref={container} className="min-h-0 flex-1" />
    </div>
  );
}

interface PickerProps {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
}

function ColumnPicker({ label, value, options, onChange }: PickerProps) {
  return (
    <label className="flex items-center gap-1 text-muted-foreground">
      {label}
      <select
        className="bg-transparent text-foreground"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function point(
  row: Row,
  time: string,
  value: string,
): { time: UTCTimestamp; value: number } {
  const raw = row[time];
  const ms =
    typeof raw === "string"
      ? Date.parse(raw)
      : typeof raw === "number"
        ? raw
        : NaN;
  const v = row[value];
  return {
    time: Math.floor(ms / 1000) as UTCTimestamp,
    value: typeof v === "number" ? v : NaN,
  };
}
```

A native `<select>` is used here rather than the shadcn `Select` so the built-in stays short; the picker is secondary to the chart.

- [ ] **Step 5: Contract text**

In `src/quarry/agent/context.py` `CONTRACT`, change the hook lines to:

```
  Default export: a component receiving one prop, datasets: string[] (the names you passed, in order).
  useQuery(spec): {status:"loading"} | {status:"success", rows, schema, rowCount, truncated} | {status:"error", message}
```

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && cd ..
uv run pytest tests/components tests/agent/test_context.py -q && uv run ruff check src tests && uv run mypy src
git add src web tests && git commit -m "feat: add data table and time series built-in views"
```

---

### Task 9: Server: snapshots, repair prompts, atomic step updates

**Files:**

- Modify: `src/quarry/server/store.py` (`update_step`), `src/quarry/server/service.py` (`RepairRequest`, `StepRequest.repair`, `record_snapshot`, `start_prompt(repair=)`), `src/quarry/server/app.py` (snapshot route, repair passthrough)
- Test: `tests/server/test_store.py`, `tests/server/test_app.py`

**Interfaces:**

- Produces: `SessionStore.update_step(session_id, step)`; `POST /sessions/{id}/steps/{step_id}/snapshots` body `{state, queries}` → `{"count": n}` (404 unknown step or no view, 409 step still running); `StepRequest.repair: RepairRequest | None`; the composed repair prompt.
- Consumes: `Snapshot`, `View`, `Step` from `models.py`; `_write_atomic`.

- [ ] **Step 1: Failing tests**

Append to `tests/server/test_store.py`:

```python
def test_update_step_rewrites_in_place(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="fake", model="m"))
    first = step(0)
    store.append_step(meta.id, first)
    store.update_step(meta.id, first.model_copy(update={"note": "changed"}))
    assert store.get(meta.id).steps[0].note == "changed"
    assert store.next_index(meta.id) == 1
    with pytest.raises(KeyError):
        store.update_step(meta.id, step(5))
```

Append to `tests/server/test_app.py`:

```python
def view_turn(call_id: str) -> AssistantTurn:
    return AssistantTurn(
        text="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="render_view",
                input={"component_id": "data-table", "datasets": ["df"], "initial_state": "{}"},
            )
        ],
        stop="tool_use",
    )


def test_snapshot_appends_to_persisted_step(tmp_path: Path) -> None:
    client = make_client(tmp_path, [py("c1", "df = pl.DataFrame({'a': [1]})"), view_turn("c2"), end()])
    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "show"}).json()["id"]
    wait_idle(client, sid)
    body = {"state": {"sort": None}, "queries": [{"dataset": "df", "limit": 1000}]}
    assert client.post(f"/sessions/{sid}/steps/{step_id}/snapshots", json=body).json() == {"count": 1}
    snapshots = client.get(f"/sessions/{sid}").json()["steps"][0]["view"]["snapshots"]
    assert snapshots[0]["state"] == {"sort": None}
    assert snapshots[0]["queries"] == body["queries"]
    assert client.post(f"/sessions/{sid}/steps/nope/snapshots", json=body).status_code == 404


def test_snapshot_rejected_for_step_without_view(tmp_path: Path) -> None:
    client = make_client(tmp_path, [py("c1", "x = 1"), end()])
    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "x"}).json()["id"]
    wait_idle(client, sid)
    body = {"state": {}, "queries": []}
    assert client.post(f"/sessions/{sid}/steps/{step_id}/snapshots", json=body).status_code == 404


def test_repair_prompt_includes_source_and_error(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "df = pl.DataFrame({'a': [1]})"), view_turn("c2"), end(), end("fixed")])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "show"}).json()["id"]
    wait_idle(client, sid)
    body = {"prompt": "Fix the view.", "repair": {"step_id": step_id, "error": '"d3" is not available'}}
    client.post(f"/sessions/{sid}/steps", json=body)
    wait_idle(client, sid)
    steps = client.get(f"/sessions/{sid}").json()["steps"]
    prompt = steps[1]["prompt"]
    assert '"d3" is not available' in prompt
    assert "export default" in prompt
    assert prompt.endswith("Fix the view.")
    last_user = [m for m in provider.calls[-1][1] if m.role == "user"][-1]
    assert "export default" in last_user.text
```

`render_view` needs `data-table` in the builtin library, which Task 8 added. Run: `uv run pytest tests/server -q` — fails.

- [ ] **Step 2: Implement**

`store.py`, add after `append_step`:

```python
    def update_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        target = self._session_dir(session_id) / "steps" / f"{step.index:04d}.json"
        if not target.exists():
            raise KeyError(step.id)
        _write_atomic(target, step.model_dump_json(by_alias=True, indent=2))
```

`service.py`:

```python
MAX_SNAPSHOTS: Final = 500


class RepairRequest(BaseModel):
    step_id: str
    error: str


class StepRequest(BaseModel):
    prompt: str
    repair: RepairRequest | None = None


class StepNotFound(Exception):
    pass
```

Change `start_prompt`:

````python
    def start_prompt(self, session_id: str, prompt: str, repair: RepairRequest | None = None) -> Step:
        if repair is not None:
            prompt = self._repair_prompt(session_id, repair, prompt)
        step = self._begin(session_id, kind="prompt", prompt=prompt, code="")
        self._start(session_id, self._run_prompt, (session_id, step, prompt))
        return step

    def _repair_prompt(self, session_id: str, repair: RepairRequest, prompt: str) -> str:
        step = self._find_step(session_id, repair.step_id)
        if step.view is None:
            raise StepNotFound(repair.step_id)
        return (
            f"The view from step {step.index + 1} failed to mount in the browser with:\n"
            f"{repair.error}\n\nIts source:\n```tsx\n{step.view.source}\n```\n\n{prompt}"
        )

    def record_snapshot(
        self, session_id: str, step_id: str, state: dict[str, Json], queries: list[dict[str, Json]]
    ) -> int:
        with self._lock:
            running = self._running.get(session_id)
            if running is not None and running.id == step_id:
                raise SessionBusy()
            step = self._find_step(session_id, step_id)
            if step.view is None:
                raise StepNotFound(step_id)
            snapshots = [*step.view.snapshots, Snapshot(ts=now_iso(), state=state, queries=queries)]
            view = step.view.model_copy(update={"snapshots": snapshots[-MAX_SNAPSHOTS:]})
            self._store.update_step(session_id, step.model_copy(update={"view": view}))
            return len(view.snapshots)

    def _find_step(self, session_id: str, step_id: str) -> Step:
        for step in self._store.get(session_id).steps:
            if step.id == step_id:
                return step
        raise StepNotFound(step_id)
````

Import `Snapshot`, `now_iso` from `models`, `Json` from `quarry.query.spec`, `Final` from typing.

`app.py`:

```python
class SnapshotRequest(BaseModel):
    state: dict[str, Json] = Field(default_factory=dict)
    queries: list[dict[str, Json]] = Field(default_factory=list)
```

Change the steps route to pass `repair`:

```python
    @api.post("/sessions/{session_id}/steps", status_code=202)
    def post_step(session_id: str, body: StepRequest) -> Step:
        session_or_404(session_id)
        try:
            return service.start_prompt(session_id, body.prompt, body.repair)
        except SessionBusy as exc:
            raise HTTPException(status_code=409, detail="a step is already running") from exc
        except StepNotFound as exc:
            raise HTTPException(status_code=404, detail=f"no view on step {exc}") from exc
```

Keep whatever the current route already does for `KernelDead`; add the `StepNotFound` branch. Add:

```python
    @api.post("/sessions/{session_id}/steps/{step_id}/snapshots")
    def post_snapshot(session_id: str, step_id: str, body: SnapshotRequest) -> dict[str, int]:
        session_or_404(session_id)
        try:
            count = service.record_snapshot(session_id, step_id, body.state, body.queries)
        except StepNotFound as exc:
            raise HTTPException(status_code=404, detail=f"no view on step {exc}") from exc
        except SessionBusy as exc:
            raise HTTPException(status_code=409, detail="step is still running") from exc
        return {"count": count}
```

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: record view snapshots and repair prompts for failed mounts"
```

---

### Task 10: Host app: shell, sessions, step column, prompt, polling

**Files:**

- Create: `web/src/host/api/context.tsx`, `web/src/host/api/hooks.ts`, `web/src/host/components/SessionRail.tsx`, `web/src/host/components/StepCard.tsx`, `web/src/host/components/DatasetChips.tsx`, `web/src/host/components/CodeDrawer.tsx`, `web/src/host/components/PromptBox.tsx`, `web/src/host/components/TokenMissing.tsx`, `web/src/host/containers/SessionPage.tsx`, `web/src/host/containers/StepList.tsx`
- Modify: `web/src/host/App.tsx`, `web/src/host/main.tsx`
- Test: `web/src/host/components/PromptBox.test.tsx`, `web/src/host/components/StepCard.test.tsx`, `web/src/host/api/hooks.test.tsx`

**Interfaces:**

- Produces: `ApiProvider` / `useApi()`; hooks `useSessions`, `useSession(id)` (polls at 750 ms while the last step is running), `useSessionStatus(id)` (same cadence), `useCreateSession`, `useSubmitPrompt(id)`, `useInterrupt(id)`, `useRestart(id)`; presentational components with props only; `SessionPage` container.
- Consumes: `ApiClient`, `keys`, Stage 2 route shapes.

- [ ] **Step 1: Failing tests**

`web/src/host/components/PromptBox.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PromptBox } from "./PromptBox";

describe("PromptBox", () => {
  it("submits on Enter and clears", () => {
    const onSubmit = vi.fn();
    render(
      <PromptBox
        running={false}
        onSubmit={onSubmit}
        onStop={() => undefined}
      />,
    );
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "show prices" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("show prices");
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("disables input and offers Stop while running", () => {
    const onStop = vi.fn();
    render(<PromptBox running onSubmit={() => undefined} onStop={onStop} />);
    expect(screen.getByRole("textbox")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });
});
```

`web/src/host/components/StepCard.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Step } from "@/shared/api-types";
import { StepCard } from "./StepCard";

const base: Step = {
  id: "s1",
  index: 0,
  kind: "prompt",
  prompt: "show prices",
  code: "prices = pl.DataFrame()",
  status: "ok",
  error: null,
  note: "Loaded prices",
  stdout_tail: "",
  stderr_tail: "",
  reads: [],
  writes: ["prices"],
  defines: [],
  datasets: [
    { name: "prices", backing: "polars", schema: [], rows: 10, preview: [] },
  ],
  view: null,
  created_at: "2026-10-08T00:00:00Z",
  duration_ms: 1200,
};

describe("StepCard", () => {
  it("shows prompt, note, dataset chips and a collapsed code drawer", () => {
    render(<StepCard step={base} index={1} />);
    expect(screen.getByText("show prices")).toBeTruthy();
    expect(screen.getByText("Loaded prices")).toBeTruthy();
    expect(screen.getByText("prices")).toBeTruthy();
    expect(screen.queryByText("prices = pl.DataFrame()")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Code" }));
    expect(screen.getByText("prices = pl.DataFrame()")).toBeTruthy();
  });

  it("shows the traceback on error", () => {
    const failed: Step = {
      ...base,
      status: "error",
      error: {
        type: "KeyError",
        message: "'x'",
        traceback: "Traceback...KeyError: 'x'",
      },
    };
    render(<StepCard step={failed} index={1} />);
    expect(screen.getByText(/KeyError: 'x'/)).toBeTruthy();
  });
});
```

`web/src/host/api/hooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "./context";
import { ApiClient } from "./client";
import { useSession } from "./hooks";

function wrapper(client: ApiClient) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={client}>{children}</ApiProvider>
    </QueryClientProvider>
  );
}

describe("useSession", () => {
  it("polls while the last step is running", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      const status = calls < 3 ? "running" : "ok";
      const body = {
        meta: {
          id: "s1",
          title: "t",
          created_at: "",
          provider: { name: "f", model: "m" },
        },
        steps: [
          {
            id: "x",
            index: 0,
            kind: "prompt",
            prompt: "p",
            code: "",
            status,
            error: null,
            note: "",
            stdout_tail: "",
            stderr_tail: "",
            reads: [],
            writes: [],
            defines: [],
            datasets: [],
            view: null,
            created_at: "",
            duration_ms: 0,
          },
        ],
      };
      return new Response(JSON.stringify(body), { status: 200 });
    };
    const { result } = renderHook(() => useSession("s1"), {
      wrapper: wrapper(new ApiClient("t", fetchImpl)),
    });
    await waitFor(
      () => expect(result.current.data?.steps[0]?.status).toBe("ok"),
      { timeout: 5000 },
    );
    expect(calls).toBeGreaterThanOrEqual(3);
  });
});
```

- [ ] **Step 2: API context and hooks**

`web/src/host/api/context.tsx`:

```tsx
import { createContext, useContext, type ReactNode } from "react";
import type { ApiClient } from "./client";

const ApiContext = createContext<ApiClient | null>(null);

export function ApiProvider({
  client,
  children,
}: {
  client: ApiClient;
  children: ReactNode;
}) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (client === null) throw new Error("ApiProvider missing");
  return client;
}
```

`web/src/host/api/hooks.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Session, SessionStatus, StepRequest } from "@/shared/api-types";
import { useApi } from "./context";
import { keys } from "./keys";

const POLL_MS = 750;

const sessionRunning = (session: Session | undefined): boolean =>
  session?.steps.at(-1)?.status === "running";

export function useSessions() {
  const api = useApi();
  return useQuery({
    queryKey: keys.sessions(),
    queryFn: () => api.listSessions(),
  });
}

export function useSession(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.session(id),
    queryFn: () => api.getSession(id),
    refetchInterval: (query) =>
      sessionRunning(query.state.data) ? POLL_MS : false,
  });
}

export function useSessionStatus(id: string, running: boolean) {
  const api = useApi();
  return useQuery<SessionStatus>({
    queryKey: keys.status(id),
    queryFn: () => api.getStatus(id),
    refetchInterval: running ? POLL_MS : 5000,
  });
}

export function useCreateSession() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => api.createSession(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sessions() }),
  });
}

export function useSubmitPrompt(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StepRequest) => api.postStep(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session(id) }),
  });
}

export function useInterrupt(id: string) {
  const api = useApi();
  return useMutation({ mutationFn: () => api.interrupt(id) });
}

export function useRestart(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.restart(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session(id) }),
  });
}
```

`GET /sessions/{id}` already includes the in-memory running step (Stage 2 `service.get`), so polling the session itself is enough to drive the step column; status is polled for kernel state and `last_error`.

- [ ] **Step 3: Presentational components**

`web/src/host/components/PromptBox.tsx`:

```tsx
import { useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface PromptBoxProps {
  running: boolean;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

export function PromptBox({ running, onSubmit, onStop }: PromptBoxProps) {
  const [text, setText] = useState("");
  const submit = () => {
    const prompt = text.trim();
    if (prompt === "" || running) return;
    onSubmit(prompt);
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };
  return (
    <div className="flex items-end gap-3 border-t border-border bg-card px-8 py-4">
      <Textarea
        value={text}
        disabled={running}
        placeholder={
          running ? "Working on the last step" : "Ask about the data"
        }
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        className="max-w-[880px] flex-1 resize-none font-sans"
      />
      {running ? (
        <Button variant="outline" onClick={onStop}>
          Stop
        </Button>
      ) : (
        <Button onClick={submit}>Run</Button>
      )}
    </div>
  );
}
```

`web/src/host/components/DatasetChips.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import type { DatasetMeta } from "@/shared/api-types";

export function DatasetChips({ datasets }: { datasets: DatasetMeta[] }) {
  if (datasets.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {datasets.map((d) => (
        <Badge
          key={d.name}
          variant="secondary"
          className="gap-1.5 font-mono text-xs"
          title={`${d.schema.length} columns`}
        >
          <span>{d.name}</span>
          {d.rows !== null && (
            <span className="text-muted-foreground">
              {d.rows.toLocaleString()}
            </span>
          )}
        </Badge>
      ))}
    </div>
  );
}
```

`web/src/host/components/CodeDrawer.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function CodeDrawer({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  if (code.trim() === "") return null;
  return (
    <div>
      <Button
        variant="ghost"
        size="xs"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Code
      </Button>
      {open && (
        <pre className="mt-1 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
          {code}
        </pre>
      )}
    </div>
  );
}
```

`web/src/host/components/StepCard.tsx`:

```tsx
import type { ReactNode } from "react";
import type { Step } from "@/shared/api-types";
import { CodeDrawer } from "./CodeDrawer";
import { DatasetChips } from "./DatasetChips";

interface StepCardProps {
  step: Step;
  index: number;
  view?: ReactNode;
}

const RULE: Record<Step["status"], string> = {
  running: "bg-[var(--status-running)]",
  ok: "bg-[var(--status-ok)]",
  error: "bg-[var(--status-error)]",
  interrupted: "bg-[var(--status-interrupted)]",
};

const LABEL: Record<Step["status"], string> = {
  running: "Running",
  ok: "Done",
  error: "Failed",
  interrupted: "Stopped",
};

export function StepCard({ step, index, view }: StepCardProps) {
  return (
    <article
      className="grid grid-cols-[2.5rem_3px_1fr] gap-x-4"
      aria-label={`Step ${index}`}
    >
      <div className="pt-0.5 text-right font-mono text-sm text-muted-foreground">
        {index}
      </div>
      <div className={`rounded-full ${RULE[step.status]}`} />
      <div className="flex min-w-0 flex-col gap-3 pb-8">
        {step.prompt !== null && (
          <p className="text-base leading-6">{step.prompt}</p>
        )}
        <p className="flex gap-4 text-sm text-muted-foreground">
          <span>{LABEL[step.status]}</span>
          {step.duration_ms > 0 && (
            <span>{(step.duration_ms / 1000).toFixed(1)} s</span>
          )}
        </p>
        {step.note !== "" && <p className="text-sm">{step.note}</p>}
        {step.error !== null && (
          <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs text-destructive">
            {step.error.traceback || step.error.message}
          </pre>
        )}
        {view}
        <DatasetChips datasets={step.datasets} />
        <CodeDrawer code={step.code} />
      </div>
    </article>
  );
}
```

`web/src/host/components/SessionRail.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import type { SessionMeta } from "@/shared/api-types";

interface SessionRailProps {
  sessions: SessionMeta[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}

export function SessionRail({
  sessions,
  activeId,
  onSelect,
  onCreate,
}: SessionRailProps) {
  return (
    <nav className="flex h-full w-[232px] flex-col gap-4 border-r border-border bg-card px-4 py-5">
      <h1 className="text-xl font-semibold">Quarry</h1>
      <Button variant="outline" size="sm" onClick={onCreate}>
        New session
      </Button>
      <ul className="flex flex-col gap-0.5 overflow-y-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              aria-current={s.id === activeId ? "page" : undefined}
              onClick={() => onSelect(s.id)}
              className="w-full truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted aria-[current=page]:bg-muted aria-[current=page]:text-primary"
            >
              {s.title}
            </button>
          </li>
        ))}
      </ul>
      {sessions.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Start a session to explore data.
        </p>
      )}
    </nav>
  );
}
```

`web/src/host/components/TokenMissing.tsx`:

```tsx
export function TokenMissing() {
  return (
    <main className="mx-auto max-w-[560px] px-8 py-16">
      <h1 className="text-xl font-semibold">Open Quarry from its link</h1>
      <p className="mt-3 text-sm text-muted-foreground">
        The address needs the token printed by{" "}
        <code className="font-mono">quarry serve</code>. Copy the full link from
        the terminal, including the part after #.
      </p>
    </main>
  );
}
```

- [ ] **Step 4: Containers and App**

`web/src/host/containers/StepList.tsx` (Task 11 replaces the `view` slot with the live frame):

```tsx
import type { ReactNode } from "react";
import type { Step } from "@/shared/api-types";
import { StepCard } from "../components/StepCard";

interface StepListProps {
  steps: Step[];
  renderView?: (step: Step) => ReactNode;
}

export function StepList({ steps, renderView }: StepListProps) {
  if (steps.length === 0) {
    return (
      <p className="px-8 py-10 text-sm text-muted-foreground">
        Ask for data to start. Try "load the prices cache for 2024".
      </p>
    );
  }
  return (
    <div className="flex flex-col px-8 py-8">
      {steps.map((step) => (
        <StepCard
          key={step.id}
          step={step}
          index={step.index + 1}
          view={step.view && renderView ? renderView(step) : undefined}
        />
      ))}
    </div>
  );
}
```

`web/src/host/containers/SessionPage.tsx`:

```tsx
import { useState } from "react";
import { PromptBox } from "../components/PromptBox";
import { SessionRail } from "../components/SessionRail";
import {
  useCreateSession,
  useInterrupt,
  useSession,
  useSessions,
  useSubmitPrompt,
} from "../api/hooks";
import { StepList } from "./StepList";

export function SessionPage() {
  const sessions = useSessions();
  const create = useCreateSession();
  const [activeId, setActiveId] = useState<string | null>(null);
  const current = activeId ?? sessions.data?.[0]?.id ?? null;

  return (
    <div className="flex h-screen">
      <SessionRail
        sessions={sessions.data ?? []}
        activeId={current}
        onSelect={setActiveId}
        onCreate={() =>
          create.mutate("Untitled", {
            onSuccess: (meta) => setActiveId(meta.id),
          })
        }
      />
      {current === null ? (
        <main className="flex-1" />
      ) : (
        <SessionColumn key={current} id={current} />
      )}
    </div>
  );
}

function SessionColumn({ id }: { id: string }) {
  const session = useSession(id);
  const submit = useSubmitPrompt(id);
  const interrupt = useInterrupt(id);
  const steps = session.data?.steps ?? [];
  const running = steps.at(-1)?.status === "running" || submit.isPending;

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="max-w-[944px]">
          {submit.isError && (
            <p className="px-8 pt-4 text-sm text-destructive">
              {submit.error.message}
            </p>
          )}
          <StepList steps={steps} />
        </div>
      </div>
      <PromptBox
        running={running}
        onSubmit={(prompt) => submit.mutate({ prompt })}
        onStop={() => interrupt.mutate()}
      />
    </main>
  );
}
```

`web/src/host/App.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { readToken } from "./api/auth";
import { ApiClient } from "./api/client";
import { ApiProvider } from "./api/context";
import { TokenMissing } from "./components/TokenMissing";
import { SessionPage } from "./containers/SessionPage";

export function App() {
  const [token] = useState(() => readToken(window.location.hash));
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1 } } }),
  );
  const [client] = useState(() =>
    token === null ? null : new ApiClient(token),
  );
  if (client === null) return <TokenMissing />;
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <SessionPage />
      </ApiProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 5: Verify by hand and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build
cd .. && uv run quarry serve --port 8765   # prints the link; open it in a browser
```

Create a session, send a prompt (a real key is needed for the agent; without one, use `POST /steps/manual` via curl to see a step land). Reload mid-step: the running step stays, polling continues, the box stays disabled. Then:

```bash
git add web && git commit -m "feat: add session rail, step column and prompt box"
```

---

### Task 11: Host app: live views, fix this, kernel restart

**Files:**

- Create: `web/src/host/containers/ViewFrameContainer.tsx`, `web/src/host/components/KernelBanner.tsx`
- Modify: `web/src/host/containers/SessionPage.tsx`, `web/src/host/containers/StepList.tsx`
- Test: `web/src/host/containers/ViewFrameContainer.test.tsx`

**Interfaces:**

- Produces: `ViewFrameContainer { sessionId, step, onRepair }` owning one `HostBridge` per view, answering `query` via `ApiClient.query`, `schema` via the datasets list (cached per session with `keys.datasets`), and posting snapshots; `KernelBanner { status, lastError, onRestart }`.
- Consumes: `HostBridge`, `ViewFrame`, `useRestart`, `useSessionStatus`.

- [ ] **Step 1: Failing test**

`web/src/host/containers/ViewFrameContainer.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Step } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { ViewFrameContainer } from "./ViewFrameContainer";

const step: Step = {
  id: "s1",
  index: 0,
  kind: "prompt",
  prompt: "p",
  code: "",
  status: "ok",
  error: null,
  note: "",
  stdout_tail: "",
  stderr_tail: "",
  reads: [],
  writes: [],
  defines: [],
  datasets: [],
  view: {
    component_id: "inline",
    content_hash: "h",
    source: "export default () => null",
    initial_state: {},
    datasets: ["df"],
    snapshots: [],
  },
  created_at: "",
  duration_ms: 0,
};

function mount(onRepair = vi.fn()) {
  const fetchImpl = vi.fn(async (url: string) => {
    if (url.endsWith("/snapshots"))
      return new Response(JSON.stringify({ count: 1 }), { status: 200 });
    if (url.endsWith("/query"))
      return new Response(
        JSON.stringify({
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: 0,
          truncated: false,
        }),
        { status: 200 },
      );
    return new Response("[]", { status: 200 });
  });
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <ViewFrameContainer sessionId="sess" step={step} onRepair={onRepair} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  const iframe = screen.getByTitle("View for step 1") as HTMLIFrameElement;
  const send = (data: unknown) =>
    window.dispatchEvent(
      new MessageEvent("message", { data, source: iframe.contentWindow }),
    );
  return { fetchImpl, send, onRepair };
}

describe("ViewFrameContainer", () => {
  it("posts snapshots for stateChanged", async () => {
    const { fetchImpl, send } = mount();
    await act(async () => {
      send({
        type: "stateChanged",
        viewId: "s1",
        state: { k: 1 },
        queries: [],
      });
    });
    await vi.waitFor(() =>
      expect(
        fetchImpl.mock.calls.some(
          ([u]) => u === "/sessions/sess/steps/s1/snapshots",
        ),
      ).toBe(true),
    );
  });

  it("shows the error overlay and starts a repair", async () => {
    const { send, onRepair } = mount();
    await act(async () => {
      send({
        type: "error",
        viewId: "s1",
        message: '"d3" is not available in views',
      });
    });
    expect(screen.getByText('"d3" is not available in views')).toBeTruthy();
    screen.getByRole("button", { name: "Fix this view" }).click();
    expect(onRepair).toHaveBeenCalledWith({
      step_id: "s1",
      error: '"d3" is not available in views',
    });
  });
});
```

- [ ] **Step 2: Implement**

`web/src/host/containers/ViewFrameContainer.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { Column, RepairRequest, Step } from "@/shared/api-types";
import { useApi } from "../api/context";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import { ViewFrame } from "../components/ViewFrame";

interface ViewFrameContainerProps {
  sessionId: string;
  step: Step;
  onRepair: (repair: RepairRequest) => void;
}

export function ViewFrameContainer({
  sessionId,
  step,
  onRepair,
}: ViewFrameContainerProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [error, setError] = useState<string | null>(null);
  // Snapshots append to step.view on every poll, so the effect keys on the content hash and
  // reads the (immutable) source, initial state and datasets through a ref.
  const viewRef = useRef(step.view);
  viewRef.current = step.view;
  const contentHash = step.view?.content_hash ?? null;
  const ownDatasets = step.datasets;

  // One bridge per iframe for its lifetime; the window listener is the effect's only job.
  useEffect(() => {
    const frame = frameRef.current;
    const view = viewRef.current;
    if (frame === null || view === null || contentHash === null) return;
    // The step already carries the schema of everything it wrote; only datasets from earlier
    // steps need the API, fetched fresh so a view never sees a list from before its step ran.
    const schemaFor = async (dataset: string): Promise<Column[]> => {
      const own = ownDatasets.find((d) => d.name === dataset);
      if (own !== undefined) return own.schema;
      const datasets = await queryClient.fetchQuery({
        queryKey: keys.datasets(sessionId),
        queryFn: () => api.datasets(sessionId),
        staleTime: 0,
      });
      const match = datasets.find((d) => d.name === dataset);
      if (match === undefined) throw new Error(`unknown dataset ${dataset}`);
      return match.schema;
    };
    const bridge = new HostBridge({
      viewId: step.id,
      frame: {
        postMessage: (m, origin) => frame.contentWindow?.postMessage(m, origin),
      },
      isFrame: (source) => source === frame.contentWindow,
      onQuery: (spec) => api.query(sessionId, spec),
      onSchema: schemaFor,
      onStateChanged: (state, queries) => {
        void api.postSnapshot(sessionId, step.id, { state, queries });
      },
      onError: (message) => setError(message),
    });
    const stop = bridge.listen(window);
    setError(null);
    bridge.mount({
      source: view.source,
      initialState: view.initial_state,
      datasets: view.datasets,
    });
    return stop;
  }, [api, queryClient, sessionId, step.id, contentHash, ownDatasets]);

  if (step.view === null) return null;
  return (
    <ViewFrame
      ref={frameRef}
      title={`View for step ${step.index + 1}`}
      error={error}
      onFix={() => error !== null && onRepair({ step_id: step.id, error })}
    />
  );
}
```

`web/src/host/components/KernelBanner.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import type { KernelStatus } from "@/shared/api-types";

interface KernelBannerProps {
  kernel: KernelStatus | undefined;
  lastError: string | null;
  restarting: boolean;
  onRestart: () => void;
}

export function KernelBanner({
  kernel,
  lastError,
  restarting,
  onRestart,
}: KernelBannerProps) {
  if (kernel?.status !== "dead") return null;
  return (
    <div className="flex items-center gap-4 border-b border-border bg-card px-8 py-3 text-sm">
      <span className="text-destructive">
        The Python kernel stopped{lastError ? `: ${lastError}` : "."}
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={restarting}
        onClick={onRestart}
      >
        Restart kernel
      </Button>
      <span className="text-muted-foreground">
        Restarting replays every finished step.
      </span>
    </div>
  );
}
```

Update `StepList` to accept `renderView` (already in Task 10) and `SessionColumn` in `SessionPage.tsx`:

```tsx
function SessionColumn({ id }: { id: string }) {
  const session = useSession(id);
  const submit = useSubmitPrompt(id);
  const interrupt = useInterrupt(id);
  const restart = useRestart(id);
  const steps = session.data?.steps ?? [];
  const running = steps.at(-1)?.status === "running" || submit.isPending;
  const status = useSessionStatus(id, running);

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <KernelBanner
        kernel={status.data?.kernel}
        lastError={status.data?.last_error ?? null}
        restarting={restart.isPending}
        onRestart={() => restart.mutate()}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="max-w-[944px]">
          {submit.isError && (
            <p className="px-8 pt-4 text-sm text-destructive">
              {submit.error.message}
            </p>
          )}
          <StepList
            steps={steps}
            renderView={(step) => (
              <ViewFrameContainer
                sessionId={id}
                step={step}
                onRepair={(repair) =>
                  submit.mutate({
                    prompt: "Fix the view so it mounts.",
                    repair,
                  })
                }
              />
            )}
          />
        </div>
      </div>
      <PromptBox
        running={running}
        onSubmit={(prompt) => submit.mutate({ prompt })}
        onStop={() => interrupt.mutate()}
      />
    </main>
  );
}
```

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build
git add web && git commit -m "feat: mount step views in the host with repair and kernel restart"
```

---

### Task 12: Playwright end-to-end, CI, README

**Files:**

- Create: `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_ui.py`
- Modify: `pyproject.toml` (dev group), `.github/workflows/ci.yml`, `README.md`

**Interfaces:**

- Produces: a `quarry_server` fixture (uvicorn in a thread on an ephemeral port, `create_app` with a scripted `FakeProvider`, `static_dir` pointing at the built UI); two browser tests; CI that builds the web app before the Python checks.

- [ ] **Step 1: Dependencies**

```bash
uv add --group dev "pytest-playwright>=0.10"
uv run playwright install chromium
```

- [ ] **Step 2: Fixture**

`tests/e2e/conftest.py`:

```python
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn
from quarry.config import QuarryConfig
from quarry.server.app import create_app

STATIC = Path(__file__).resolve().parents[2] / "src" / "quarry" / "static"
TOKEN = "e2e-token"


@dataclass(slots=True)
class RunningServer:
    base_url: str
    token: str


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def serve(tmp_path: Path) -> Iterator[Callable[[list[AssistantTurn]], RunningServer]]:
    if not (STATIC / "index.html").exists():
        pytest.skip("web build missing; run `npm run build` in web/")
    servers: list[uvicorn.Server] = []

    def start(turns: list[AssistantTurn]) -> RunningServer:
        config = QuarryConfig(root=tmp_path)
        app = create_app(
            config=config,
            token=TOKEN,
            provider_factory=lambda _cfg: FakeProvider(turns),
            static_dir=STATIC,
        )
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        servers.append(server)
        return RunningServer(base_url=f"http://127.0.0.1:{port}", token=TOKEN)

    yield start
    for server in servers:
        server.should_exit = True
```

`uvicorn.Server.run` skips signal handling off the main thread (uvicorn 0.29+), so running it in a daemon thread is supported.

- [ ] **Step 3: Tests**

`tests/e2e/test_ui.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page, expect

from quarry.agent.types import AssistantTurn, ToolCall
from tests.e2e.conftest import RunningServer

pl_df = "df = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [101.5, 102.25]})"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(
        text="", tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})], stop="tool_use"
    )


def render(call_id: str, component_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id,
        name="render_view",
        input={"component_id": component_id, "datasets": ["df"], "initial_state": "{}"},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def write(call_id: str, source: str) -> AssistantTurn:
    call = ToolCall(id=call_id, name="write_view", input={"source": source, "datasets": ["df"], "initial_state": "{}"})
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def open_session(page: Page, server: RunningServer, prompt: str) -> None:
    page.goto(f"{server.base_url}/#token={server.token}")
    page.get_by_role("button", name="New session").click()
    box = page.get_by_role("textbox")
    expect(box).to_be_enabled()
    box.fill(prompt)
    box.press("Enter")


def test_table_view_round_trip(serve: Callable[[list[AssistantTurn]], RunningServer], page: Page) -> None:
    server = serve([py("c1", pl_df), render("c2", "data-table"), end("Here is df")])
    open_session(page, server, "show df")
    expect(page.get_by_text("Here is df")).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_text("102.25")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("textbox")).to_be_enabled()


def test_refused_import_offers_fix(serve: Callable[[list[AssistantTurn]], RunningServer], page: Page) -> None:
    bad = 'import * as d3 from "d3";\nexport default function V() { return <div>{typeof d3}</div>; }'
    server = serve([py("c1", pl_df), write("c2", bad), end("drew it"), end("fixed")])
    open_session(page, server, "custom view")
    expect(page.get_by_text('"d3" is not available in views', exact=False)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Fix this view").click()
    expect(page.get_by_text("fixed", exact=True)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Its source:")).to_be_visible()
```

If the first test fails because the iframe never renders (CSP blocking chunks), apply Review Focus item 2's loopback host-source fallback in `runtime.html`; do not drop `connect-src 'none'` or the sandbox.

- [ ] **Step 4: CI**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
        working-directory: web
      - run: npm run check
        working-directory: web
      - run: npm test
        working-directory: web
      - run: npm run build
        working-directory: web
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.11
      - run: uv sync --locked
      - run: uv run playwright install --with-deps chromium
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests
      - run: uv run mypy src
      - run: uv run pytest -v
      - run: uv build
      - run: unzip -l dist/*.whl | grep quarry/static/index.html
```

- [ ] **Step 5: README**

Add after the Stage 2 section:

````markdown
## Using the browser UI (Stage 3)

Build the UI once, then serve:

```bash
cd web && npm ci && npm run build && cd ..
uv run quarry serve
```

Open the printed link (it carries the token after `#`). From a laptop, forward the port first with the `ssh -L` line the banner prints.

### Developing the UI

```bash
uv run quarry serve --port 8765          # terminal 1
cd web && QUARRY_PORT=8765 npm run dev    # terminal 2, open http://localhost:5173/#token=<token>
```

Vite proxies `/sessions` and `/healthz` to the Python server. `npm run check`, `npm test`, and `npm run build` must pass before a commit; the Playwright tests under `tests/e2e` run only when `src/quarry/static/index.html` exists.
````

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run build && cd ..
uv run pytest tests/e2e -v
uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src
npx prettier --write README.md
git add tests pyproject.toml uv.lock .github README.md && git commit -m "test: add browser end-to-end tests and build the UI in CI"
```

---

## Done when

- `quarry serve` opened from its link lets a researcher create a session, run a prompt, see the step with its note, dataset chips and collapsed code, and interact with the table or chart.
- A refused import or render error shows in the view slot with "Fix this view", which starts a repair step carrying the source and the error.
- Reloading the page mid-step resumes polling with the token intact.
- A dead kernel shows "Restart kernel"; restart replays steps.
- `useViewState` changes land in the step's `view.snapshots` on disk.
- `npm run check`, `npm test`, `npm run build`, `uv run pytest` (including `tests/e2e`), ruff, mypy all pass locally and in CI; the wheel contains `quarry/static/index.html`.
