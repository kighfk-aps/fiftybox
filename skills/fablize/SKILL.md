---
name: fablize
description: A harness that makes Opus (or any Claude model) behave like Fable — it enforces seeing a task through to the end, with evidence and verification, as procedure. Use when starting a multi-step task (2+ sequential stories), long autonomous work, debugging or root-cause investigation, building render/executable artifacts (HTML, SVG, games, charts), or when the user says "fablize", "see it through", "verify as you go", "split into goals".
---

# fablize — run Opus like Fable

> Principle: a harness cannot raise a model's ceiling. It makes the model go all the way to its own ceiling — by enforcing verification, completion, and investigation as procedure. When the capability ceiling is the blocker (open-ended creative detail, self-driven discovery), escalate (§4).
>
> Apply only what the task signals (smallest matching discipline; overlap only when genuinely multi-category). When installed always-on, this routing is automatic.

## 1. Multi-story loop (2+ sequential stories)

Decompose into sequential stories and complete one at a time, producing evidence as you go. Use the fiftybox orchestration system (`orchestrate.py`) for multi-story task management — it already handles decomposition, checkpointing, and verification gates.

Rules: each story must produce concrete evidence before proceeding to the next. The final story must verify the end-to-end result. Single-step tasks skip this loop.

## 2. Deep investigation (debugging / unknown cause / review)

Read and follow `skills/fablize/investigation-protocol.txt`: reproduce first → form 3+ competing hypotheses → gather evidence per hypothesis → trace the full causal chain (removing the symptom is not removing the defect) → verify before and after → report the hypotheses you rejected. For reviews, report everything including low-confidence findings and filter in a separate step.

## 3. Working style (always)

Lead with the outcome. Stay within the requested scope (no incidental refactors or abstractions). Ground every completion claim in a tool result from this session. Confirm before destructive or hard-to-reverse actions.

## 4. At the capability ceiling (escalate)

Signals you have hit the model's ceiling: stuck on the same problem 2+ times; open-ended creation where detail itself is the value; deep review that needs out-of-spec discovery. These are capability, not procedure, and a harness cannot fill them. In order: (1) adaptive thinking already scales with difficulty — recommend `/effort xhigh` to the user to push the current model to its ceiling; (2) if still short, hand off to a stronger model in a fresh session with an evidence package (symptoms, attempts, failure point, repro); (3) otherwise report the limit honestly and name where a human must step in.

## Install (always-on)

The Stop hook (`finish-the-work.sh`) is registered in `.claude/settings.json` and active for all sessions in this project.
