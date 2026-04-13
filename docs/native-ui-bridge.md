# Native vkdt Bridge

This repo expects the real `vkdt` application to own editing state.

## Upstream Integration Points

- `src/gui/gui.h`: `vkdt.graph_dev`
- `src/gui/render_darkroom.c`: `darkroom_enter()`, `darkroom_leave()`, `darkroom_process()`
- `src/gui/render_darkroom.h`: parameter editing flow in `render_darkroom_widget()`
- `src/gui/widget_nodes.h`: node editor connections and module context menus
- `src/pipe/graph-history.h`: history-wrapped module and connection edits
- `src/pipe/graph-io.c`: graph read and write helpers
- `src/pipe/module.c`: module add/remove helpers
- `src/pipe/modules/api.h`: typed parameter setters

## Recommended Native Bridge Design

1. Collect the current image state from `vkdt.graph_dev`
2. Expose current editable controls as a capability manifest
3. Send chat turns to `/v1/chat/stream`
4. Apply streamed operations on the main UI thread
5. Trigger rerender through the normal `vkdt` runflags and processing path
6. Post refreshed preview bytes to `/v1/chat/render`

## Operation Shape

The backend expects either:

- direct control operations against `actionPath`
- explicit graph actions for native node structure edits

Suggested `actionPath` conventions:

- `module/<name>:<instance>/param/<param>`
- `graph/module/add`
- `graph/module/remove`
- `graph/connect`
- `graph/disconnect`
- `graph/activate-module`

## Why This Pivot

Using the native app keeps the visible `vkdt` session authoritative, lets the user see real node edits as they happen, and avoids maintaining a second fake editing UI in the repo.
