#include "gui/bridge.h"

#include "core/tools.h"
#include "core/log.h"
#include "gui/gui.h"
#include "pipe/graph-io.h"
#include "pipe/graph-history.h"
#include "pipe/modules/api.h"

#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

typedef struct dt_bridge_state_t
{
  int enabled;
  int active_turn;
  int next_turn;
  int next_batch;
  pid_t helper_pid;
  char session_dir[PATH_MAX];
  char app_session_id[64];
  char conversation_id[64];
  char image_session_id[64];
  char prompt[1024];
  char status[256];
}
dt_bridge_state_t;

static dt_bridge_state_t bridge = {0};

static void dt_bridge_set_status(const char *message)
{
  snprintf(bridge.status, sizeof(bridge.status), "%s", message ? message : "");
}

const char *dt_bridge_status()
{
  return bridge.status;
}

static int dt_bridge_file_exists(const char *filename)
{
  struct stat st;
  return !stat(filename, &st);
}

static int dt_bridge_mkdir_p(const char *dirname)
{
  char tmp[PATH_MAX];
  snprintf(tmp, sizeof(tmp), "%s", dirname);
  for(char *p=tmp+1;*p;p++) if(*p == '/')
  {
    *p = 0;
    mkdir(tmp, 0755);
    *p = '/';
  }
  return mkdir(tmp, 0755) && errno != EEXIST;
}

static void dt_bridge_percent_decode(char *text)
{
  char *src = text;
  char *dst = text;
  while(*src)
  {
    if(src[0] == '%' && src[1] && src[2])
    {
      char hex[3] = {src[1], src[2], 0};
      *dst++ = (char)strtol(hex, 0, 16);
      src += 3;
    }
    else if(*src == '+')
    {
      *dst++ = ' ';
      src++;
    }
    else
    {
      *dst++ = *src++;
    }
  }
  *dst = 0;
}

static int dt_bridge_parse_module_path(
    const char *action_path,
    char *module,
    size_t module_sz,
    char *inst,
    size_t inst_sz,
    char *param,
    size_t param_sz)
{
  if(strncmp(action_path, "module/", 7)) return 1;
  const char *modinst = action_path + 7;
  const char *param_part = strstr(modinst, "/param/");
  if(!param_part) return 1;
  char tmp[128];
  snprintf(tmp, MIN((int)sizeof(tmp), (int)(param_part - modinst) + 1), "%s", modinst);
  char *sep = strchr(tmp, ':');
  if(!sep) return 1;
  *sep = 0;
  snprintf(module, module_sz, "%s", tmp);
  snprintf(inst, inst_sz, "%s", sep+1);
  snprintf(param, param_sz, "%s", param_part + 7);
  dt_bridge_percent_decode(param);
  return 0;
}

static int dt_bridge_apply_numeric(const char *action_path, const char *mode, const char *value_text)
{
  char module[64], inst[64], param_name[128];
  if(dt_bridge_parse_module_path(action_path, module, sizeof(module), inst, sizeof(inst), param_name, sizeof(param_name))) return 1;
  int modid = dt_module_get(&vkdt.graph_dev, dt_token(module), dt_token(inst));
  if(modid < 0) return 2;
  int parid = dt_module_get_param(vkdt.graph_dev.module[modid].so, dt_token(param_name));
  if(parid < 0) return 3;
  const dt_ui_param_t *param = vkdt.graph_dev.module[modid].so->param[parid];
  dt_graph_run_t flags = s_graph_run_record_cmd_buf;
  if(param->type == dt_token("float"))
  {
    float *dst = (float *)dt_module_param_float(vkdt.graph_dev.module + modid, parid);
    float old = dst[0];
    float value = atof(value_text);
    dst[0] = !strcmp(mode, "delta") ? old + value : value;
    if(vkdt.graph_dev.module[modid].so->check_params)
      flags = vkdt.graph_dev.module[modid].so->check_params(vkdt.graph_dev.module + modid, parid, 0, &old);
  }
  else if(param->type == dt_token("int"))
  {
    int *dst = (int *)dt_module_param_int(vkdt.graph_dev.module + modid, parid);
    int old = dst[0];
    int value = atoi(value_text);
    dst[0] = !strcmp(mode, "delta") ? old + value : value;
    if(vkdt.graph_dev.module[modid].so->check_params)
      flags = vkdt.graph_dev.module[modid].so->check_params(vkdt.graph_dev.module + modid, parid, 0, &old);
  }
  else return 4;
  vkdt.graph_dev.runflags = flags | s_graph_run_record_cmd_buf;
  vkdt.graph_dev.active_module = modid;
  dt_graph_history_append(&vkdt.graph_dev, modid, parid, 0.0);
  vkdt.wstate.busy += 2;
  return 0;
}

static int dt_bridge_apply_graph_command(char **field, int field_cnt)
{
  if(field_cnt <= 0) return 1;
  if(!strcmp(field[0], "graph-add-module") && field_cnt >= 3)
  {
    if(dt_module_add_with_history(&vkdt.graph_dev, dt_token(field[1]), dt_token(field[2])) >= 0)
    {
      vkdt.graph_dev.runflags = s_graph_run_all;
      vkdt.wstate.busy += 2;
      return 0;
    }
    return 2;
  }
  if(!strcmp(field[0], "graph-remove-module") && field_cnt >= 3)
  {
    dt_module_remove_with_history(&vkdt.graph_dev, dt_token(field[1]), dt_token(field[2]));
    vkdt.graph_dev.runflags = s_graph_run_all;
    vkdt.wstate.busy += 2;
    return 0;
  }
  if(!strcmp(field[0], "graph-connect") && field_cnt >= 7)
  {
    int m0 = dt_module_get(&vkdt.graph_dev, dt_token(field[1]), dt_token(field[2]));
    int m1 = dt_module_get(&vkdt.graph_dev, dt_token(field[4]), dt_token(field[5]));
    if(m0 < 0 || m1 < 0) return 3;
    int c0 = dt_module_get_connector(vkdt.graph_dev.module+m0, dt_token(field[3]));
    int c1 = dt_module_get_connector(vkdt.graph_dev.module+m1, dt_token(field[6]));
    if(c0 < 0 || c1 < 0) return 4;
    if(dt_module_connect_with_history(&vkdt.graph_dev, m0, c0, m1, c1)) return 5;
    vkdt.graph_dev.runflags = s_graph_run_all;
    vkdt.wstate.busy += 2;
    return 0;
  }
  if(!strcmp(field[0], "graph-disconnect") && field_cnt >= 4)
  {
    int m1 = dt_module_get(&vkdt.graph_dev, dt_token(field[1]), dt_token(field[2]));
    if(m1 < 0) return 6;
    int c1 = dt_module_get_connector(vkdt.graph_dev.module+m1, dt_token(field[3]));
    if(c1 < 0) return 7;
    if(dt_module_connect_with_history(&vkdt.graph_dev, -1, -1, m1, c1)) return 8;
    vkdt.graph_dev.runflags = s_graph_run_all;
    vkdt.wstate.busy += 2;
    return 0;
  }
  if(!strcmp(field[0], "graph-activate-module") && field_cnt >= 3)
  {
    int modid = dt_module_get(&vkdt.graph_dev, dt_token(field[1]), dt_token(field[2]));
    if(modid < 0) return 9;
    vkdt.graph_dev.active_module = modid;
    vkdt.graph_dev.runflags = s_graph_run_all;
    vkdt.wstate.busy += 2;
    return 0;
  }
  return 10;
}

static int dt_bridge_submit_prompt()
{
  uint32_t imgid = dt_db_current_imgid(&vkdt.db);
  if(imgid == -1u || !bridge.prompt[0]) return 1;
  snprintf(bridge.image_session_id, sizeof(bridge.image_session_id), "img-%u", imgid);
  bridge.active_turn = bridge.next_turn++;
  bridge.next_batch = 1;
  char graph_path[PATH_MAX+100];
  dt_db_image_path(&vkdt.db, imgid, graph_path, sizeof(graph_path));
  dt_graph_write_config_ascii(&vkdt.graph_dev, graph_path);
  char turn_dir[PATH_MAX];
  snprintf(turn_dir, sizeof(turn_dir), "%s/turn-%04d", bridge.session_dir, bridge.active_turn);
  if(dt_bridge_mkdir_p(turn_dir)) return 2;
  char meta_path[PATH_MAX], prompt_path[PATH_MAX];
  snprintf(meta_path, sizeof(meta_path), "%s/meta.txt", turn_dir);
  snprintf(prompt_path, sizeof(prompt_path), "%s/prompt.txt", turn_dir);
  FILE *meta = fopen(meta_path, "wb");
  FILE *prompt = fopen(prompt_path, "wb");
  if(!meta || !prompt)
  {
    if(meta) fclose(meta);
    if(prompt) fclose(prompt);
    return 3;
  }
  fprintf(meta, "app_session_id=%s\n", bridge.app_session_id);
  fprintf(meta, "image_session_id=%s\n", bridge.image_session_id);
  fprintf(meta, "conversation_id=%s\n", bridge.conversation_id);
  fprintf(meta, "turn_id=turn-%04d\n", bridge.active_turn);
  fprintf(meta, "view=%s\n", vkdt.view_mode == s_view_nodes ? "nodes" : "darkroom");
  fprintf(meta, "image_name=%s\n", graph_path);
  fprintf(meta, "image_id=%u\n", imgid);
  fprintf(meta, "graph_path=%s\n", graph_path);
  fprintf(prompt, "%s\n", bridge.prompt);
  fclose(meta);
  fclose(prompt);
  bridge.prompt[0] = 0;
  dt_bridge_set_status("Agent turn started");
  return 0;
}

void dt_bridge_open_prompt()
{
  if(!bridge.enabled) return;
  vkdt.wstate.popup = s_popup_agent_prompt;
  vkdt.wstate.popup_appearing = 1;
}

void dt_bridge_render_modal()
{
  struct nk_rect bounds = { vkdt.state.center_x+0.2f*vkdt.state.center_wd, vkdt.state.center_y+0.25f*vkdt.state.center_ht,
    0.6f*vkdt.state.center_wd, 0.25f*vkdt.state.center_ht };
  if(!nk_begin(&vkdt.ctx, "agent prompt", bounds, NK_WINDOW_NO_SCROLLBAR | NK_WINDOW_TITLE))
  {
    vkdt.wstate.popup = 0;
    nk_end(&vkdt.ctx);
    return;
  }
  const float row_height = vkdt.ctx.style.font->height + 2 * vkdt.ctx.style.tab.padding.y;
  nk_layout_row_dynamic(&vkdt.ctx, row_height, 1);
  nk_label(&vkdt.ctx, "Describe the edit you want the agent to make", NK_TEXT_LEFT);
  if(vkdt.wstate.popup_appearing) nk_edit_focus(&vkdt.ctx, 0);
  nk_flags ret = nk_edit_string_zero_terminated(&vkdt.ctx, NK_EDIT_BOX|NK_EDIT_SIG_ENTER, bridge.prompt, sizeof(bridge.prompt), nk_filter_default);
  vkdt.wstate.popup_appearing = 0;
  nk_layout_row_dynamic(&vkdt.ctx, row_height, 2);
  if(nk_button_label(&vkdt.ctx, "cancel")) vkdt.wstate.popup = 0;
  if((ret & NK_EDIT_COMMITED) || nk_button_label(&vkdt.ctx, "send"))
  {
    if(!dt_bridge_submit_prompt()) vkdt.wstate.popup = 0;
    else dt_gui_notification("failed to start agent turn");
  }
  if(bridge.status[0])
  {
    nk_layout_row_dynamic(&vkdt.ctx, row_height, 1);
    nk_label(&vkdt.ctx, bridge.status, NK_TEXT_LEFT);
  }
  nk_end(&vkdt.ctx);
}

static void dt_bridge_spawn_helper()
{
  const char *helper_cmd = getenv("VKDT_AGENT_HELPER_CMD");
  if(!helper_cmd || !helper_cmd[0]) return;
  pid_t pid = 0;
  char command[PATH_MAX*2];
  snprintf(command, sizeof(command), "%s --session-dir \"%s\"", helper_cmd, bridge.session_dir);
  char *argv[] = {"/bin/sh", "-lc", command, 0};
  if(!posix_spawn(&pid, "/bin/sh", 0, 0, argv, environ)) bridge.helper_pid = pid;
}

void dt_bridge_init()
{
  memset(&bridge, 0, sizeof(bridge));
  bridge.enabled = getenv("VKDT_AGENT_DISABLE") ? 0 : 1;
  bridge.next_turn = 1;
  if(!bridge.enabled) return;
  snprintf(bridge.session_dir, sizeof(bridge.session_dir), "%s", getenv("VKDT_AGENT_SESSION_DIR") ? getenv("VKDT_AGENT_SESSION_DIR") : "/tmp/vkdt-agent-session");
  dt_bridge_mkdir_p(bridge.session_dir);
  snprintf(bridge.app_session_id, sizeof(bridge.app_session_id), "app-%d", getpid());
  snprintf(bridge.conversation_id, sizeof(bridge.conversation_id), "conv-%ld", time(0));
  dt_bridge_set_status("Agent bridge ready");
  dt_bridge_spawn_helper();
}

void dt_bridge_cleanup()
{
  if(bridge.helper_pid > 0)
  {
    kill(bridge.helper_pid, SIGTERM);
    waitpid(bridge.helper_pid, 0, WNOHANG);
  }
}

static void dt_bridge_ack_batch(const char *turn_dir, int batch)
{
  char ack_path[PATH_MAX], graph_path[PATH_MAX+100];
  snprintf(ack_path, sizeof(ack_path), "%s/ops-%04d.applied", turn_dir, batch);
  FILE *f = fopen(ack_path, "wb");
  if(f) { fprintf(f, "ok\n"); fclose(f); }
  dt_db_image_path(&vkdt.db, dt_db_current_imgid(&vkdt.db), graph_path, sizeof(graph_path));
  dt_graph_write_config_ascii(&vkdt.graph_dev, graph_path);
}

static void dt_bridge_finish_turn(const char *turn_dir, const char *filename)
{
  char path[PATH_MAX];
  snprintf(path, sizeof(path), "%s/%s", turn_dir, filename);
  FILE *f = fopen(path, "rb");
  char message[512] = {0};
  if(f)
  {
    fread(message, 1, sizeof(message)-1, f);
    fclose(f);
  }
  if(message[0]) dt_gui_notification("agent: %s", message);
  bridge.active_turn = 0;
  bridge.next_batch = 1;
  dt_bridge_set_status(filename[0] == 'e' ? "Agent turn failed" : "Agent turn complete");
}

void dt_bridge_poll_mainthread()
{
  if(!bridge.enabled || bridge.active_turn <= 0) return;
  char turn_dir[PATH_MAX];
  snprintf(turn_dir, sizeof(turn_dir), "%s/turn-%04d", bridge.session_dir, bridge.active_turn);
  char final_path[PATH_MAX], error_path[PATH_MAX], ops_path[PATH_MAX];
  snprintf(final_path, sizeof(final_path), "%s/final.txt", turn_dir);
  snprintf(error_path, sizeof(error_path), "%s/error.txt", turn_dir);
  if(dt_bridge_file_exists(error_path))
  {
    dt_bridge_finish_turn(turn_dir, "error.txt");
    return;
  }
  if(dt_bridge_file_exists(final_path))
  {
    dt_bridge_finish_turn(turn_dir, "final.txt");
    return;
  }
  snprintf(ops_path, sizeof(ops_path), "%s/ops-%04d.txt", turn_dir, bridge.next_batch);
  if(!dt_bridge_file_exists(ops_path)) return;
  FILE *f = fopen(ops_path, "rb");
  if(!f) return;
  char line[1024];
  while(fgets(line, sizeof(line), f))
  {
    size_t len = strlen(line);
    while(len && (line[len-1] == '\n' || line[len-1] == '\r')) line[--len] = 0;
    if(!len) continue;
    char *field[8] = {0};
    int field_cnt = 0;
    char *saveptr = 0;
    for(char *tok = strtok_r(line, "\t", &saveptr); tok && field_cnt < 8; tok = strtok_r(0, "\t", &saveptr))
      field[field_cnt++] = tok;
    if(field_cnt >= 4 && (!strcmp(field[0], "set-float") || !strcmp(field[0], "set-bool") || !strcmp(field[0], "set-choice")))
      dt_bridge_apply_numeric(field[1], field[2], field[3]);
    else dt_bridge_apply_graph_command(field, field_cnt);
  }
  fclose(f);
  dt_bridge_ack_batch(turn_dir, bridge.next_batch);
  bridge.next_batch++;
  dt_bridge_set_status("Applied agent operation batch");
}
