"""Each run writes a folder runs/<name>/ with three files:

    full.json     full trajectories (prompts, outputs, grading)
    results.json  scores + per-rubric verdicts, no prompts
    prompts.md    per-step prompt review: the shared actor context once, then each
                  attempt's injected delta, with judge/critic prompts folded away

Rewritten per task and swapped in atomically. load/inspect/metrics take the run
folder or its full.json.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict


def save(traj, out):
    os.makedirs(out, exist_ok=True)
    full = os.path.join(out, "full.json")
    trajs = load(out) if os.path.exists(full) else []
    trajs.append(asdict(traj))
    _write(full, _json(trajs))
    _write(os.path.join(out, "results.json"), _json(_results_view(trajs)))
    _write(os.path.join(out, "prompts.md"), _prompts_md(trajs))


def load(out):
    """Trajectories as dicts; `out` is the run folder or its full.json."""
    path = os.path.join(out, "full.json") if os.path.isdir(out) else out
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def inspect(out, task_id):
    """Reprint one trajectory step by step, untruncated."""
    for traj in load(out):
        if traj["task_id"] == task_id:
            print(f"task {traj['task_id']} | metric={traj['metric']} | model={traj['model']} "
                  f"| feedback={traj['feedback_mode']} | success={traj['success']} "
                  f"| best_score={traj['best_score']}")
            for step in traj["steps"]:
                print(_render_step(step, limit=0))
            return
    raise KeyError(f"task {task_id!r} not found in {out}")


def print_step(step, limit=3000):
    print(_render_step(asdict(step), limit))


def _results_view(trajs):
    return [
        {
            "task_id": t["task_id"],
            "metric": t["metric"],
            "model": t["model"],
            "feedback_mode": t["feedback_mode"],
            "success": t["success"],
            "best_score": t["best_score"],
            "attempts": [
                {
                    "attempt": s["attempt_index"] + 1,
                    "success": s["result"]["success"],
                    "score": s["result"]["score"],
                    "requirement_status": (s["result"].get("private") or {}).get("requirement_status"),
                    "failed_requirement_count": (s["result"].get("private") or {}).get("failed_requirement_count"),
                    "total_requirements": (s["result"].get("private") or {}).get("total_requirements"),
                }
                for s in t["steps"]
            ],
        }
        for t in trajs
    ]


def _prompts_md(trajs):
    out = []
    for t in trajs:
        verdict = "PASS" if t["success"] else "FAIL"
        out.append(f"# TASK {t['task_id']} — {t['metric']} / {t['feedback_mode']} — {verdict} (best {t['best_score']})\n")
        base = t.get("task_prompt") or ""
        if base:
            out.append(_fold(f"Shared actor context — sent every attempt ({len(base)} chars)", base))
        for s in t["steps"]:
            r = s["result"]
            priv = r.get("private") or {}
            failed = [i + 1 for i, v in enumerate(priv.get("requirement_status") or []) if v == "no"]
            mark = "PASS" if r["success"] else "FAIL"
            out.append(f"## Attempt {s['attempt_index'] + 1} — {mark}" + (f" (failed: {failed})" if failed else ""))
            delta = s["prompt"]
            if base and delta.startswith(base):
                delta = delta[len(base):].lstrip("\n")
            out.append("**Actor delta** — added to the shared context:")
            out.append(_block(delta or "(shared context only)"))
            if priv.get("judge_prompt"):
                out.append(_fold("Judge prompt", priv["judge_prompt"]))
            if priv.get("critic_prompt"):
                out.append(_fold(f"Critic prompt ({t['feedback_mode']})", priv["critic_prompt"]))
        out.append("")
    return "\n".join(out)


def _block(text):
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)   # outlast any backticks in the body
    return f"{fence}\n{text}\n{fence}"


def _fold(summary, text):
    return f"<details><summary>{summary}</summary>\n\n{_block(text)}\n\n</details>\n"


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _truncate(text, limit):
    text = "" if text is None else str(text)
    if limit and len(text) > limit:
        return text[:limit] + f"\n…[truncated {len(text) - limit} chars; full text in results folder]"
    return text


def _render_step(step, limit):
    r = step["result"]
    status = (r.get("private") or {}).get("requirement_status")
    verdict = "PASS" if r["success"] else "FAIL"
    lines = [
        f"\n--- attempt {step['attempt_index'] + 1} ---",
        "PROMPT:",
        _truncate(step["prompt"], limit),
        "\nOUTPUT:",
        _truncate(step["output"], limit),
        f"\nVERDICT: {verdict}  score={r['score']}",
    ]
    if status:
        lines.append(f"rubrics: {status}")
    if step.get("feedback"):
        lines.append("\nFEEDBACK:")
        lines.append(_truncate(step["feedback"], limit))
    return "\n".join(lines)
