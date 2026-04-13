# Protocol v1

`vkdtAgent` is now built for a native `vkdt` UI bridge, not a browser-side editing shell.

## Request

`POST /v1/chat`
`POST /v1/chat/stream`

The native app submits:

- `session`
- `uiContext`
- `message`
- `capabilityManifest`
- `imageSnapshot`
- `refinement`

The backend plans against the live native app state and returns operations. The app applies them locally and posts refreshed preview bytes back to `/v1/chat/render` during streamed runs.

## Tool Surface

Codex only sees these bounded tools:

- `get_image_state`
- `get_preview_image`
- `get_playbook`
- `apply_operations`
- `end`

`apply_operations` is app-driven:

1. Codex proposes native vkdt operations
2. backend exposes them in streamed progress
3. native vkdt applies them in the real UI session
4. native vkdt posts a refreshed preview to `/v1/chat/render`
5. Codex continues from the refreshed state

## Native Integration

The running `vkdt` app should remain the source of truth for:

- graph/session state
- current module parameters
- current node connections
- undo/history
- rendered preview

This mirrors the darktable-style architecture rather than the old browser-side graph execution approach.
