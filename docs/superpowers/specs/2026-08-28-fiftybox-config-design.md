# fiftybox-config: provider/model availability toggle tool

Date: 2026-08-28
Status: approved (brainstorming), pending implementation plan

## Problem

`fiftybox-execute`/`fiftybox-local` hardcode which CLI tools (Pi, Codex,
CommandCode, Grok, opencode) and which models under each tool are usable, and
in what priority order, directly as prose tables inside `SKILL.md`. When the
user's subscription status changes (a plan lapses, a new one starts, a model
gets renamed), the only way to reflect that is editing `SKILL.md` by hand.

There is no single place that says "here is what I can actually use right
now" that both a human and the orchestration skills can read.

## Goal

A small, dependency-free settings store plus an interactive TUI that lets the
user check on/off which CLI tools and which models under each tool are
available, and edit that list, without touching `SKILL.md`. The execution
skills read this store to decide which providers to preflight-check and
which provider fills each priority slot in the lane allocator.

## Non-goals

- Not a subscription/auth checker. The user manually reflects reality; the
  tool does not call out to `cmd`, `grok inspect`, etc. to auto-detect status
  (Step 0 preflight in `fiftybox-execute` still does that, but only for
  providers this config marks enabled).
- Not a lane-priority reordering UI. The priority order per task category
  (security/core -> lane 1, screen/browser -> lane 2, etc.) stays conceptually
  fixed; only which provider currently occupies a slot changes based on
  enabled/disabled state.
- Not project-scoped. Subscriptions belong to accounts on this machine, not
  to any one repo.

## Components

### 1. Config file — `~/.claude/fiftybox-config.json`

Global, machine-level, shared by every project's `fiftybox-execute` and
`fiftybox-local` runs.

```json
{
  "lane_priority": ["codex-write", "pi", "grok", "commandcode"],
  "providers": {
    "codex-write": {
      "enabled": true,
      "models": { "gpt-5.6-luna": true, "gpt-5.6-terra": false }
    },
    "pi": {
      "enabled": true,
      "backends": {
        "zai-coding": { "models": { "glm-5.3-flash": true } },
        "opencode-go": { "models": { "deepseek-v4-flash": true } },
        "modal-qwen38": { "models": { "qwen3.8-27b-q4_k_m": true } }
      }
    },
    "grok": {
      "enabled": true,
      "models": { "grok-4.6": true }
    },
    "commandcode": {
      "enabled": true,
      "models": { "qwen/qwen3.7-flash": true, "zai-org/glm-5.2": true }
    },
    "opencode": {
      "enabled": true
    }
  }
}
```

Notes:
- `lane_priority` is an ordered list of provider keys. It is not edited
  through the TUI in this iteration (no reordering UI); it exists in the file
  so a future iteration, or a manual edit, can change it without a schema
  migration.
- A `true`/`false` leaf under `models` means "this model is a usable
  candidate" / "listed but currently off". Removing a model entirely (via the
  TUI's delete) removes the key rather than setting it false, so stale
  renamed models don't accumulate.
- `pi` nests `backends` because Pi is itself a multi-backend router
  (`zai-coding`, `opencode-go`, `modal-qwen38`), matching how
  `fiftybox-execute`/`fiftybox-local` already address it.
- `opencode` has no `models` map because `fiftybox-local` discovers its free
  tier live every run (`discover_free_models.py`); the config only gates
  whether that discovery runs at all.

### 2. `skills/fiftybox-config/scripts/config_lib.py`

Pure logic module, no curses import, so it is unit-testable without a TTY.

Responsibilities:
- `load_config(path) -> dict`: read the JSON file; if missing, write and
  return a copy of the packaged default (see Install section); if the file
  exists but fails to parse, move it to `<path>.bak`, write a fresh default,
  and return it (with a flag the caller can use to warn the user).
- `save_config(path, data)`: write JSON back, pretty-printed, stable key
  order.
- `first_enabled_model(provider_dict) -> str | None`: given a provider's
  `models` map (or, for `pi`, a chosen backend's `models` map), return the
  first key whose value is `true`, else `None`.
- `resolve_lane(config, lane_priority_index) -> provider_key | None`:
  starting at `lane_priority[index]`, walk forward through `lane_priority`
  (wrapping is not needed — the list has exactly one entry per priority slot
  today) returning the first provider whose `enabled` is `true`; `None` if
  every provider in the list is disabled.
- `add_model(config, provider, model, backend=None)` /
  `remove_model(config, provider, model, backend=None)`: mutate the in-memory
  dict; TUI calls these then `save_config`.

### 3. `skills/fiftybox-config/scripts/config_tui.py`

Thin `curses` UI on top of `config_lib.py`. Stdlib `curses` only — no new
dependency, consistent with every other script in this repo (all stdlib:
`argparse`, `json`, `subprocess`, etc.; `rich`/`questionary` are not
installed and won't be added for this).

Screen: a tree — provider rows (checkbox for `enabled`), expandable to show
their model rows (checkbox for on/off). Keys:
- Up/Down: move
- Space: toggle checkbox on the selected row
- Enter: expand/collapse a provider's model list
- `a`: add a model under the selected provider (prompts for a name inline)
- `d`: delete the selected model row
- `s`: save and exit
- `q`: quit without saving

This tool is meant to be run **by the human**, directly in a terminal (the
existing convention in this project: suggest `! python3 ...` so it runs in
the user's own terminal rather than through an agent, since curses needs a
real keyboard/TTY that Claude cannot drive).

### 4. `skills/fiftybox-config/SKILL.md`

Describes `/fiftybox-config`: what the tool is for, and that invoking it
means telling the user to run the TUI themselves via `!`, not running it as
Claude. Documents the config file path and schema for reference so future
Claude sessions reading this skill understand what `fiftybox-execute`/
`fiftybox-local` are consuming.

## Integration with fiftybox-execute / fiftybox-local

### fiftybox-execute

**Step 0 — Preflight**: before checking any specific provider, read
`~/.claude/fiftybox-config.json`. Only run the preflight check (CommandCode
`cc_preflight.py`, `grok inspect`, `pi --list-models zai-coding`, `codex exec
--help`) for providers whose `enabled` is `true`. A disabled provider is
treated as absent — no preflight call, no error surfaced for it.

**Model Resolution / lane allocator table**: the four priority rows keep
their task-category meaning (security/core, screen/browser/visual,
external-API/deploy, everything else) but the *provider filling each row* is
computed, not hardcoded:

> Row *i* is filled by `resolve_lane(config, i)`. If every provider in
> `lane_priority` is disabled for that slot's position onward, that priority
> level has no provider; if this happens for a task actually assigned to that
> row, stop and tell the user to enable at least one provider via
> `/fiftybox-config`.

Model choice within the resolved provider comes from
`first_enabled_model(...)`; if a provider is enabled but has zero enabled
models, treat it as if disabled for resolution purposes and fall through
`lane_priority`.

**Explicit `--provider`/`--model` flags still bypass all of this** — they are
the user's explicit override today, and stay that way; the config only feeds
the *default* lane allocator path.

### fiftybox-local

- `providers.opencode.enabled` gates whether `discover_free_models.py` runs
  at all this invocation.
- `providers.pi.backends.modal-qwen38` gates whether `modal-qwen38` is added
  as an always-on candidate in the candidate pool step.

## Install (`install.sh`)

Add an install block for `fiftybox-config` following the existing
`fiftybox-local` pattern: copy `SKILL.md` and `scripts/*.py` to
`~/.claude/skills/fiftybox-config/`.

Separately, ship `skills/fiftybox-config/config/default-config.json` (the
schema shown above) in the repo. `install.sh` copies it to
`~/.claude/fiftybox-config.json` **only if that file does not already
exist** — reinstalling this repo must never clobber a user's current
enabled/disabled choices.

## Testing

- `tests/test_fiftybox_config_lib.py`: unit tests against `config_lib.py`
  directly (no curses, runs in any CI): default-file creation on missing
  path, corrupt-JSON recovery (`.bak` written, fresh default returned),
  `first_enabled_model` behavior (first true wins, `None` when all false or
  map empty), `resolve_lane` fallthrough when the first N providers in
  `lane_priority` are disabled, and the all-disabled `None` case.
- `tests/test_config_skill_doc.sh`: shell test following the existing
  `test_execute_skill_doc.sh` / `test_local_skill_doc.sh` pattern — greps
  `skills/fiftybox-config/SKILL.md` for required strings (config file path,
  the "run this yourself with `!`" instruction, schema mention).
- `tests/test_install.sh` gets a case asserting the new skill's files land
  under `~/.claude/skills/fiftybox-config/` and that a pre-existing
  `~/.claude/fiftybox-config.json` survives a re-run of `install.sh`
  untouched.

## Error handling

- Config file missing: TUI writes the packaged default on first run;
  `config_lib.load_config` does the same for any script-side reader (so
  `fiftybox-execute` never crashes on a fresh machine).
- Config file present but invalid JSON: back up to `.bak`, recreate default,
  surface a warning (TUI prints it; `fiftybox-execute`, reading via
  `config_lib`, surfaces the same warning to the user before continuing with
  defaults).
- All providers disabled (or all providers for a given lane slot disabled):
  stop the pipeline and tell the user to enable at least one provider via
  `/fiftybox-config`, rather than silently falling back to a hardcoded
  provider or a paid one.

## Out of scope for this iteration

- Auto-detecting subscription status (calling `cmd`, `grok inspect`, etc.
  from inside the config tool itself).
- Reordering `lane_priority` through the TUI.
- Per-project overrides of the global config.
