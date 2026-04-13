from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"expected snippet not found:\n{old}")
    return text.replace(old, new, 1)


def patch_file(path: Path, transform) -> None:
    original = path.read_text()
    updated = transform(original)
    path.write_text(updated)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_vkdt_native_patch.py /path/to/vkdt", file=sys.stderr)
        return 1
    target_root = Path(sys.argv[1]).resolve()
    gui_dir = target_root / "src" / "gui"
    if not gui_dir.exists():
        print(f"vkdt gui directory not found: {gui_dir}", file=sys.stderr)
        return 1

    shutil.copy2(ROOT / "native" / "vkdt-bridge.c", gui_dir / "bridge.c")
    shutil.copy2(ROOT / "native" / "vkdt-bridge.h", gui_dir / "bridge.h")

    patch_file(
        gui_dir / "flat.mk",
        lambda text: replace_once(
            replace_once(
                text,
                "GUI_O=gui/gui.o\\\n",
                "GUI_O=gui/gui.o\\\n      gui/bridge.o\\\n",
            ),
            "GUI_H=gui/gui.h\\\n",
            "GUI_H=gui/gui.h\\\n      gui/bridge.h\\\n",
        ),
    )
    patch_file(
        gui_dir / "gui.h",
        lambda text: replace_once(
            text,
            "  s_popup_add_module,\n  s_popup_edit_hotkeys,\n",
            "  s_popup_add_module,\n  s_popup_agent_prompt,\n  s_popup_edit_hotkeys,\n",
        ),
    )
    patch_file(
        gui_dir / "main.c",
        lambda text: replace_once(
            replace_once(
                replace_once(
                    replace_once(
                        text,
                        '#include "gui/view.h"\n#include "gui/api.h"\n',
                        '#include "gui/view.h"\n#include "gui/bridge.h"\n#include "gui/api.h"\n',
                    ),
                    "  dt_gui_read_tags();\n",
                    "  dt_gui_read_tags();\n  dt_bridge_init();\n",
                ),
                "    double t0 = dt_time();\n    dt_view_process();",
                "    double t0 = dt_time();\n    dt_bridge_poll_mainthread();\n    dt_view_process();",
            ),
            "  threads_global_cleanup(); // join worker threads before killing their resources\n",
            "  threads_global_cleanup(); // join worker threads before killing their resources\n  dt_bridge_cleanup();\n",
        ),
    )
    patch_file(
        gui_dir / "render_darkroom.c",
        lambda text: replace_once(
            replace_once(
                replace_once(
                    replace_once(
                        text,
                        '#include "gui/menu.h"\n#include "gui/api_gui.h"\n',
                        '#include "gui/menu.h"\n#include "gui/bridge.h"\n#include "gui/api_gui.h"\n',
                    ),
                    "  s_hotkey_menu_adjust     = 31,\n  s_hotkey_menu_modules    = 32,\n  s_hotkey_menu_rotate     = 33,\n  s_hotkey_dragkey_dec      = 34,\n  s_hotkey_dragkey_inc      = 35,\n  s_hotkey_dragkey_dec_alt  = 36,\n  s_hotkey_dragkey_inc_alt  = 37,\n  s_hotkey_dragkey_ydec     = 38,\n  s_hotkey_dragkey_yinc     = 39,\n  s_hotkey_dragkey_ydec_alt = 40,\n  s_hotkey_dragkey_yinc_alt = 41,\n  s_hotkey_count            = 42,\n",
                    "  s_hotkey_menu_adjust     = 31,\n  s_hotkey_menu_modules    = 32,\n  s_hotkey_menu_rotate     = 33,\n  s_hotkey_agent_prompt    = 34,\n  s_hotkey_dragkey_dec      = 35,\n  s_hotkey_dragkey_inc      = 36,\n  s_hotkey_dragkey_dec_alt  = 37,\n  s_hotkey_dragkey_inc_alt  = 38,\n  s_hotkey_dragkey_ydec     = 39,\n  s_hotkey_dragkey_yinc     = 40,\n  s_hotkey_dragkey_ydec_alt = 41,\n  s_hotkey_dragkey_yinc_alt = 42,\n  s_hotkey_count            = 43,\n",
                ),
                '  {"adjust",          "open key-accel chord menu",                 {GLFW_KEY_A}},\n  {"modules",         "open modules chord menu",                   {GLFW_KEY_M}},\n  {"rotate",          "open rotate chord menu",                    {GLFW_KEY_R}},\n',
                '  {"adjust",          "open key-accel chord menu",                 {GLFW_KEY_A}},\n  {"modules",         "open modules chord menu",                   {GLFW_KEY_M}},\n  {"rotate",          "open rotate chord menu",                    {GLFW_KEY_R}},\n  {"agent prompt",    "open the native agent prompt",              {GLFW_KEY_LEFT_CONTROL, GLFW_KEY_G}},\n',
            ),
            "    case s_hotkey_show_hotkeys:\n      dt_gui_dr_show_hotkeys();\n      break;\n    default: break; // menu leaders and dragkey step keys are consumed before reaching here\n",
            "    case s_hotkey_show_hotkeys:\n      dt_gui_dr_show_hotkeys();\n      break;\n    case s_hotkey_agent_prompt:\n      dt_bridge_open_prompt();\n      break;\n    default: break; // menu leaders and dragkey step keys are consumed before reaching here\n",
        ),
    )
    patch_file(
        gui_dir / "render_darkroom.h",
        lambda text: replace_once(
            replace_once(
                text,
                "#pragma once\n// some routines shared between node editor and darkroom mode\n",
                '#pragma once\n// some routines shared between node editor and darkroom mode\n#include "gui/bridge.h"\n',
            ),
            '  else if(vkdt.wstate.popup == s_popup_apply_preset)\n  {\n    if(nk_begin(&vkdt.ctx, "apply preset", bounds, NK_WINDOW_NO_SCROLLBAR | NK_WINDOW_TITLE))\n    {\n      char filename[1024] = {0};\n      uint32_t cid = dt_db_current_imgid(&vkdt.db);\n      if(cid != -1u) dt_db_image_path(&vkdt.db, cid, filename, sizeof(filename));\n      if(!strstr(vkdt.db.dirname, "examples") && !strstr(filename, "examples"))\n        dt_graph_write_config_ascii(&vkdt.graph_dev, filename);\n      static char filter[256];\n      int ok = filteredlist("presets", "presets", filter, filename, sizeof(filename), s_filteredlist_return_short);\n      if(ok) vkdt.wstate.popup = 0;\n      if(ok == 1)\n      {\n        uint32_t err_lno = render_darkroom_apply_preset(filename);\n        if(err_lno)\n          dt_gui_notification("failed to read %s line %u", filename, err_lno);\n      } // end if ok == 1\n    }\n    else vkdt.wstate.popup = 0;\n    nk_end(&vkdt.ctx);\n  }\n}',
            '  else if(vkdt.wstate.popup == s_popup_apply_preset)\n  {\n    if(nk_begin(&vkdt.ctx, "apply preset", bounds, NK_WINDOW_NO_SCROLLBAR | NK_WINDOW_TITLE))\n    {\n      char filename[1024] = {0};\n      uint32_t cid = dt_db_current_imgid(&vkdt.db);\n      if(cid != -1u) dt_db_image_path(&vkdt.db, cid, filename, sizeof(filename));\n      if(!strstr(vkdt.db.dirname, "examples") && !strstr(filename, "examples"))\n        dt_graph_write_config_ascii(&vkdt.graph_dev, filename);\n      static char filter[256];\n      int ok = filteredlist("presets", "presets", filter, filename, sizeof(filename), s_filteredlist_return_short);\n      if(ok) vkdt.wstate.popup = 0;\n      if(ok == 1)\n      {\n        uint32_t err_lno = render_darkroom_apply_preset(filename);\n        if(err_lno)\n          dt_gui_notification("failed to read %s line %u", filename, err_lno);\n      } // end if ok == 1\n    }\n    else vkdt.wstate.popup = 0;\n    nk_end(&vkdt.ctx);\n  }\n  else if(vkdt.wstate.popup == s_popup_agent_prompt)\n  {\n    dt_bridge_render_modal();\n  }\n}',
        ),
    )
    print(f"Applied vkdt native patch to {target_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
