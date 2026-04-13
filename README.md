# vkdtAgent

`vkdtAgent` is a Codex-driven RAW editing workflow built around the [vkdt](https://github.com/hanatos/vkdt) node graph. It uses a local Python backend, a live Codex app-server bridge, and a graph-first editing protocol so requests become concrete `vkdt` module, connection, and parameter edits.

`vkdt` remains the rendering engine and graph source of truth. The backend manages a working `.cfg`, renders previews and exports through `vkdt-cli`, and gives Codex a tool surface built directly on the `vkdt` module graph.

## Features

- Live Codex app-server planning loop with graph-editing tools
- Multi-turn only workflow with iterative state refresh after edits
- Built-in browser client served by the FastAPI app
- `vkdt` graph parser and serializer for `module`, `connect`, and `param` lines
- Built-in default RAW graph when no sidecar exists yet
- Built-in module catalog and adjustment surfaces covering the broader vkdt editing workflow
- Headless preview and export rendering through `vkdt-cli`
- Deterministic mock mode for smoke tests and CI

## Architecture

- `server/` contains the FastAPI backend, Codex bridge, and `vkdt` graph/runtime code
- `shared/` contains the request and response protocol models
- `docs/` documents the editing protocol and repo workflow

Request flow:

1. The client submits a prompt plus an image path and optional graph path.
2. The backend creates or loads a working `vkdt` graph.
3. Codex inspects the current graph, preview, and module catalog through structured tools.
4. Codex applies graph edits live, previewing between steps as needed.
5. Codex re-reads the current workflow state or preview after edits when it needs another pass.
6. The run completes only when Codex explicitly calls `end` with the final assistant message.
7. The backend returns the final graph state, preview, and any requested exports.

Open the client at `http://127.0.0.1:4000/`.

## Core Workflow Coverage

The built-in module catalog, adjustment surfaces, and playbooks cover a broad still-photo workflow:

- RAW ingest, hot pixel cleanup, and burst alignment
- exposure and white balance
- highlight recovery
- denoise and demosaic choices
- crop, rotate, and perspective
- lens correction and chromatic aberration cleanup
- tone mapping, dehaze, graduated filters, vignette, and film rendering
- global and local contrast or sharpening
- color grading and curves
- local adjustments with mask, draw, guided, exposure, inpaint, wavelet, and blend nodes
- negative conversion, film simulation, grain, and framing
- still export to JPEG, EXR, or web output paths

## Setup

Prerequisites:

- macOS or Linux
- `python3` 3.14+
- `uv`
- `codex` CLI installed and authenticated for live runs
- `vkdt-cli` available in `PATH`, or `VKDT_AGENT_VKDT_CLI` pointing at it

Install dependencies:

```bash
npm run bootstrap
```

Start the backend:

```bash
npm run server:start
```

By default the backend runs on `127.0.0.1:4000`.

## Testing

Run lint:

```bash
npm run backend:lint
```

Run formatting check:

```bash
npm run backend:format:check
```

Run tests:

```bash
npm run backend:test
```

Run type checking:

```bash
npm run backend:typecheck
```

Run the deterministic smoke path:

```bash
npm run agent:smoke
```

## Mock Mode

Set `VKDT_AGENT_USE_MOCK_RESPONSES=1` to exercise the API without a live Codex app-server process or a real `vkdt-cli` binary. This is what CI uses for smoke verification while preserving the same multi-turn request contract.

## Upstream vkdt Tracking

Tracked upstream metadata lives in `vkdt-upstream.json`.

Check the current tracked state against upstream:

```bash
npm run vkdt:upstream-status
```
