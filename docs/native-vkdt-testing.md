# Native vkdt Testing

This repo now includes the native `vkdt` bridge helper and a reproducible patch script for an upstream `vkdt` checkout.

## Files

- `native/vkdt_agent_bridge_helper.py`: handles `/v1/chat/stream`, `/v1/chat/render`, and preview generation via `vkdt-cli`
- `native/vkdt-bridge.c`
- `native/vkdt-bridge.h`
- `scripts/apply_vkdt_native_patch.py`: copies the bridge files into an upstream checkout and patches the required GUI files

## Apply The Native Patch

```bash
python3 scripts/apply_vkdt_native_patch.py /path/to/vkdt
```

## Build Requirements

You need the normal upstream `vkdt` system dependencies, including Vulkan headers/runtime, GLFW, ffmpeg, and `glslangValidator`.

This patch path was validated locally after installing the macOS dependencies with Homebrew.

## Run Path

1. Start the Python backend in this repo.
2. Build `vkdt` and `vkdt-cli` from the patched upstream checkout.
3. Point the app bridge at the helper:

```bash
export VK_ICD_FILENAMES=/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json
export VKDT_AGENT_HELPER_CMD="python3 /path/to/vkdtAgent/native/vkdt_agent_bridge_helper.py --backend-host 127.0.0.1 --backend-port 4000 --vkdt-cli /path/to/vkdt/bin/vkdt-cli"
export VKDT_AGENT_SESSION_DIR=/tmp/vkdt-agent-session
```

4. Launch the patched `vkdt` GUI.
5. Open an image in darkroom mode.
6. Press `Ctrl+G` to open the native agent prompt.
7. Submit an edit request.

The native app writes the live graph to the image sidecar, the helper streams the turn to the backend, applies operation batches through the app, renders refreshed previews with `vkdt-cli`, and posts those preview bytes back to the backend mid-turn.

## Local Validation

Validated in this workspace:

- backend lint, format, typecheck, tests, and smoke checks passed
- patched upstream `vkdt` binaries built successfully after installing dependencies
- resulting binaries include `bin/vkdt` and `bin/vkdt-cli`
