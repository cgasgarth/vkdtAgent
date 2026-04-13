# Protocol v1

`vkdtAgent` uses a graph-first editing protocol.

This protocol is intentionally multi-turn only. Requests must describe a live refinement run.

## Request

`POST /v1/chat`

Top-level fields:

- `schemaVersion`
- `requestId`
- `session`
- `message`
- `workspace`
- `fast`
- `refinement`

`workspace` fields:

- `imagePath`: source RAW or image path
- `graphPath`: optional existing `vkdt` sidecar graph
- `graphText`: optional inline graph content
- `sessionRoot`: optional parent directory for working files
- `previewWidth`, `previewHeight`: preview render size
- `defaultRenderFormat`: preview format, currently `o-jpg`

If neither `graphPath` nor `graphText` is provided, the backend builds a default RAW graph anchored on `imagePath`.

`refinement` must use:

- `mode: "multi-turn"`
- `enabled: true`
- `maxPasses >= 2`

## Live Agent Tools

The Codex run is limited to these tools:

- `get_workflow_state`
- `get_preview_image`
- `get_module_catalog`
- `get_playbook`
- `apply_graph_edits`
- `render_export`
- `end`

`apply_graph_edits` accepts a list of edit objects. Supported `kind` values:

- `set_param`
- `add_module`
- `remove_module`
- `connect`
- `disconnect`
- `insert_module_after`

The response from that tool includes:

- a compact summary text
- the refreshed preview image
- the updated workflow state as JSON text

The intended loop is:

1. inspect the current state or preview
2. apply a coherent batch of graph edits
3. inspect the refreshed result
4. continue iterating until satisfied
5. call `end`

## Response

The final response contains:

- `assistantMessage`
- `plan`
- `workflow`

`workflow` contains the final graph path, graph text, preview, current module summary, and any export artifacts produced during the run.
