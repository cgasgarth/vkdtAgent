#pragma once

void dt_bridge_init();
void dt_bridge_cleanup();
void dt_bridge_poll_mainthread();
void dt_bridge_open_prompt();
void dt_bridge_render_modal();
const char *dt_bridge_status();
