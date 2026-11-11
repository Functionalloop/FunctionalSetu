"""Implementation task tracker for docs/plan.md.

TASKS.md (repo root) is a checklist generated from the checkboxes in docs/plan.md.
A task is done when it is ticked in either file; this script keeps both in step.

    python scripts/tasks.py status            progress per step and the next open tasks
    python scripts/tasks.py done 4.1 [4.2 ..] tick tasks (records today's date and HEAD commit)
        [--commit SHA]                        record this commit instead of HEAD
    python scripts/tasks.py undo 4.1          untick a task in both files
    python scripts/tasks.py sync              rebuild TASKS.md after plan.md changes
    python scripts/tasks.py check             exit 1 if TASKS.md is out of date

Tasks without a number in plan.md (the Demo section) get an ID from the section
name: D.1, D.2. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "plan.md"
TASKS = ROOT / "TASKS.md"

HEADING_RE = re.compile(r"^## (.+)$")
BOX_RE = re.compile(r"^- \[( |x|X)\] \*\*(.+?)\*\*(.*)$")
ID_RE = re.compile(r"^(\d+\.\d+)\s+(.*)$")
DUE_RE = re.compile(r"\(([^()]*\b(?:Nov|Dec)\b[^()]*)\)\s*$")
TRACKED_RE = re.compile(r"^- \[( |x|X)\] \*\*([A-Z0-9]+\.\d+)\*\*(.*)$")
DONE_RE = re.compile(r"done (\d{4}-\d{2}-\d{2})")
SHA_RE = re.compile(r"`([0-9a-f]{7,40})`\s*$")


@dataclass
class Task:
    id: str
    title: str
    due: str
    done: bool
    plan_line: int  # index into plan.md lines


@dataclass
class Section:
    heading: str
    tasks: list[Task]


@dataclass
class DoneInfo:
    date: str = ""
    commit: str = ""


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def parse_plan(lines: list[str]) -> list[Section]:
    sections: list[Section] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        h = HEADING_RE.match(line)
        if h:
            sections.append(Section(h.group(1).strip(), []))
            continue
        m = BOX_RE.match(line)
        if not m:
            continue
        if not sections:
            sys.exit(f"plan.md line {i + 1}: checkbox before any '## ' heading")
        sec = sections[-1]
        bold = m.group(2).strip()
        idm = ID_RE.match(bold)
        if idm:
            tid, title = idm.group(1), idm.group(2)
        else:
            prefix = re.sub(r"[^A-Za-z]", "", sec.heading)[:1].upper() or "X"
            tid, title = f"{prefix}.{len(sec.tasks) + 1}", bold
        if tid in seen:
            sys.exit(f"plan.md line {i + 1}: duplicate task id {tid}")
        seen.add(tid)
        title = title.strip().rstrip(".:").strip()
        due = DUE_RE.search(m.group(3))
        sec.tasks.append(
            Task(tid, title, due.group(1) if due else "", m.group(1) != " ", i)
        )
    return [s for s in sections if s.tasks]


def parse_tracker() -> dict[str, tuple[bool, DoneInfo]]:
    if not TASKS.exists():
        return {}
    out: dict[str, tuple[bool, DoneInfo]] = {}
    for line in read(TASKS):
        m = TRACKED_RE.match(line)
        if not m:
            continue
        rest = m.group(3)
        d = DONE_RE.search(rest)
        c = SHA_RE.search(rest)
        out[m.group(2)] = (
            m.group(1) != " ",
            DoneInfo(d.group(1) if d else "", c.group(1) if c else ""),
        )
    return out


def head_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def bar(done: int, total: int, width: int = 20) -> str:
    filled = round(width * done / total) if total else 0
    return "█" * filled + "░" * (width - filled)


def render(sections: list[Section], info: dict[str, DoneInfo]) -> list[str]:
    all_tasks = [t for s in sections for t in s.tasks]
    done = sum(t.done for t in all_tasks)
    total = len(all_tasks)
    pct = round(100 * done / total) if total else 0
    out = [
        "# JANSETU – implementation tracker",
        "",
        "Generated from `docs/plan.md` by `scripts/tasks.py`. Full task text, files and tests are in the plan.",
        "Tick with `python scripts/tasks.py done 4.1` (or tick a box here and run `python scripts/tasks.py sync`).",
        "",
        f"**Overall: {done} / {total} done ({pct}%)** `{bar(done, total)}`",
        "",
        "| Section | Done | Progress |",
        "|---|---|---|",
    ]
    for s in sections:
        sd = sum(t.done for t in s.tasks)
        name = s.heading.split(" · ")[0]
        out.append(f"| {name} | {sd} / {len(s.tasks)} | `{bar(sd, len(s.tasks), 10)}` |")
    for s in sections:
        sd = sum(t.done for t in s.tasks)
        out += ["", f"## {s.heading} — {sd}/{len(s.tasks)}", ""]
        for t in s.tasks:
            parts = [f"- [{'x' if t.done else ' '}] **{t.id}** {t.title}"]
            if t.due:
                parts.append(f"due {t.due}")
            if t.done:
                di = info.get(t.id, DoneInfo())
                if di.date:
                    parts.append(f"done {di.date}")
                if di.commit:
                    parts.append(f"`{di.commit}`")
            out.append(" · ".join(parts))
    out.append("")
    return out


def tick_plan(lines: list[str], task: Task, done: bool) -> None:
    lines[task.plan_line] = re.sub(
        r"^- \[[ xX]\]", "- [x]" if done else "- [ ]", lines[task.plan_line], count=1
    )
    task.done = done


def build(changes: dict[str, bool] | None = None, commit: str = "") -> tuple[list[str], list[str], list[str]]:
    """Return (new plan lines, new TASKS.md lines, messages)."""
    plan_lines = read(PLAN)
    sections = parse_plan(plan_lines)
    tasks = {t.id: t for s in sections for t in s.tasks}
    tracked = parse_tracker()
    msgs: list[str] = []
    today = dt.date.today().isoformat()

    info: dict[str, DoneInfo] = {}
    for tid, (ticked, di) in tracked.items():
        if tid not in tasks:
            msgs.append(f"warning: {tid} is in TASKS.md but no longer in plan.md; dropped")
            continue
        info[tid] = di
        if ticked and not tasks[tid].done:
            tick_plan(plan_lines, tasks[tid], True)

    for tid, done in (changes or {}).items():
        if tid not in tasks:
            sys.exit(f"unknown task id {tid}; see `python scripts/tasks.py status`")
        tick_plan(plan_lines, tasks[tid], done)
        if done:
            info[tid] = DoneInfo(today, commit or head_sha())
            msgs.append(f"done: {tid} {tasks[tid].title}")
        else:
            info.pop(tid, None)
            msgs.append(f"reopened: {tid} {tasks[tid].title}")

    for t in tasks.values():
        if t.done and not info.get(t.id, DoneInfo()).date:
            info[t.id] = DoneInfo(today, info.get(t.id, DoneInfo()).commit)

    return plan_lines, render(sections, info), msgs


def cmd_status() -> None:
    sections = parse_plan(read(PLAN))
    all_tasks = [t for s in sections for t in s.tasks]
    done = sum(t.done for t in all_tasks)
    print(f"Overall {done}/{len(all_tasks)}  {bar(done, len(all_tasks))}")
    for s in sections:
        sd = sum(t.done for t in s.tasks)
        print(f"  {sd:>2}/{len(s.tasks):<2} {bar(sd, len(s.tasks), 10)}  {s.heading.split(' · ')[0]}")
    nxt = [t for t in all_tasks if not t.done][:5]
    if nxt:
        print("Next:")
        for t in nxt:
            print(f"  {t.id:<5} {t.title}" + (f"  (due {t.due})" if t.due else ""))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("sync")
    sub.add_parser("check")
    d = sub.add_parser("done")
    d.add_argument("ids", nargs="+")
    d.add_argument("--commit", default="")
    u = sub.add_parser("undo")
    u.add_argument("ids", nargs="+")
    a = p.parse_args()

    if a.cmd == "status":
        cmd_status()
        return

    changes = None
    if a.cmd == "done":
        changes = {i: True for i in a.ids}
    elif a.cmd == "undo":
        changes = {i: False for i in a.ids}

    plan_lines, tracker, msgs = build(changes, getattr(a, "commit", ""))

    if a.cmd == "check":
        stale = (not TASKS.exists()) or read(TASKS) != tracker or read(PLAN) != plan_lines
        for m in msgs:
            print(m)
        if stale:
            print("TASKS.md and docs/plan.md are out of step; run `python scripts/tasks.py sync`")
            sys.exit(1)
        print("TASKS.md matches docs/plan.md")
        return

    if read(PLAN) != plan_lines:
        write(PLAN, plan_lines)
    write(TASKS, tracker)
    for m in msgs:
        print(m)
    cmd_status()


if __name__ == "__main__":
    main()
