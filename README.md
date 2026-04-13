# vkdtAgent

`vkdtAgent` is a Codex-driven agent backend for the native [`vkdt`](https://github.com/hanatos/vkdt) UI.

The design now mirrors the darktable-style architecture:

- the running `vkdt` app is the source of truth
- the Python backend plans edits with Codex
- the native app applies operations locally in the real UI session
- the native app sends refreshed preview renders back mid-turn

## Features

- Native-UI-first architecture for `vkdt`
- Multi-turn only live edit loop
- Bounded Codex tool surface: state, preview, playbook, apply operations, end
- Dynamic capability-manifest model so the app declares what is editable
- Streamed progress and render callback flow for iterative editing
- Built-in `vkdt` module catalog and playbooks for planning guidance
- Mock mode for backend tests and CI

## Endpoints

- `POST /v1/chat`
- `POST /v1/chat/stream`
- `POST /v1/chat/cancel`
- `POST /v1/chat/render`
- `GET /health`

The backend runs on `http://127.0.0.1:4000` by default.

## Architecture

- `server/app.py`: API surface, SSE stream, cancel endpoint, render callback endpoint
- `server/bridge.py`: Codex app-server bridge and bounded tool routing
- `server/bridge_types.py`: planner bridge interface
- `server/mock_planner.py`: deterministic test planner
- `shared/protocol.py`: app/backend protocol models
- `docs/native-ui-bridge.md`: upstream `vkdt` hook points and native bridge plan

## Native vkdt Flow

1. Native `vkdt` captures the current graph, controls, history, and preview.
2. It sends a turn to `/v1/chat/stream`.
3. Codex inspects state and emits operations through `apply_operations`.
4. Native `vkdt` applies those operations in the real UI session.
5. Native `vkdt` rerenders and posts the refreshed preview to `/v1/chat/render`.
6. Codex continues iterating until it calls `end`.

## Adjustment Surfaces

The backend keeps a broad built-in planning vocabulary for `vkdt`, including:

- RAW ingest, hot pixels, denoise, demosaic, highlight recovery, alignment
- crop, rotate, perspective, lens, chromatic aberration cleanup
- exposure, white balance, tone mapping, OpenDRT, local contrast
- zones, graduated filters, vignette, dehaze
- grading, curves, sharpening, texture/detail tools
- masks, draw, guided filtering, blend, inpaint, wavelet retouching
- negative conversion, film simulation, grain, frame
- output encoding and export stages

The native app should still send the live editable control surface dynamically each turn.

## Setup

Prerequisites:

- `python3` 3.14+
- `uv`
- `codex` CLI installed and authenticated for live runs
- a native `vkdt` build patched or integrated to talk to this backend

Install dependencies:

```bash
npm run bootstrap
```

Start the backend:

```bash
npm run server:start
```

## Testing

```bash
npm run backend:lint
npm run backend:format:check
npm run backend:test
npm run backend:typecheck
npm run agent:smoke
```

## Mock Mode

Set `VKDT_AGENT_USE_MOCK_RESPONSES=1` to exercise the backend without a live Codex app-server or a patched native `vkdt` build.

## Upstream vkdt Tracking

Tracked upstream metadata lives in `vkdt-upstream.json`.

```bash
npm run vkdt:upstream-status
```
