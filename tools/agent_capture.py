#!/usr/bin/env python3
"""
8x agent capture hook.

Wired into Claude Code's UserPromptSubmit and Stop lifecycle events, so it fires
on its own for every prompt and every end-of-turn, in every session, without
anyone remembering to run it.

  UserPromptSubmit -> appends a PROMPT entry (the prompt verbatim, in full)
  Stop             -> appends a RESPONSE entry (the final assistant text of that
                      turn, in full; no thinking, no tool calls, no intermediate
                      steps)

Entries are stored append-only in a per-session JSONL journal under
STATE_DIR. The markdown log in LOG_DIR is regenerated from that journal on every
write, so the header counters stay accurate while entry bodies are never touched
after the fact.
"""

import json
import os
import sys
import datetime
import pathlib

CONFIG_PATH = pathlib.Path("/root/.claude/agent-capture.json")
STATE_DIR = pathlib.Path("/root/.claude/agent-capture-state")

DEFAULTS = {
    "log_dir": "/home/claude/agent-logs",
    "project": "unknown-project",
    "author": "unknown",
    "tool": "claude-code",
    "fallback_model": "unknown",
}


def cfg():
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(CONFIG_PATH.read_text()))
    except Exception:
        pass
    return data


def now_iso():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z"
    )


def model_from_transcript(transcript_path, fallback):
    """Most recent assistant message's model name, so a mid-build model switch is visible."""
    try:
        model = None
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") == "assistant" and msg.get("model"):
                    model = msg["model"]
        return model or fallback
    except Exception:
        return fallback


def final_response_from_transcript(transcript_path):
    """
    The text the user actually got back at the end of the turn.

    Walks the transcript, finds the last user turn that is a real human prompt,
    and concatenates the text blocks of every assistant message after it. Tool
    calls, tool results and thinking blocks are skipped -- we want what came back,
    not how it got there.
    """
    records = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return ""

    last_human = -1
    for i, rec in enumerate(records):
        if rec.get("type") != "user":
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                last_human = i
        elif isinstance(content, list):
            # a user record made only of tool_result blocks is the harness, not a person
            if any(b.get("type") == "text" for b in content if isinstance(b, dict)):
                last_human = i

    chunks = []
    for rec in records[last_human + 1:]:
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text.strip():
                        chunks.append(text)
    return "\n\n".join(chunks).strip()


def journal_path(session_id):
    return STATE_DIR / f"{session_id}.jsonl"


def meta_path(session_id):
    return STATE_DIR / f"{session_id}.meta.json"


def load_meta(session_id, conf):
    p = meta_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    started = datetime.datetime.now(datetime.timezone.utc)
    meta = {
        "session_id": session_id,
        "started_at": now_iso(),
        "date": started.strftime("%Y-%m-%d"),
        "filename": started.strftime("%Y-%m-%d_%H-%M-%S") + f"_{session_id[:8]}.md",
        "project": conf["project"],
        "author": conf["author"],
        "tool": conf["tool"],
    }
    p.write_text(json.dumps(meta, indent=2))
    return meta


def append_entry(session_id, entry):
    with open(journal_path(session_id), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_journal(session_id):
    p = journal_path(session_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def render(session_id, meta, entries, conf):
    short = session_id[:8]
    prompts = [e for e in entries if e["type"] == "PROMPT"]
    first_t = prompts[0]["timestamp"] if prompts else meta["started_at"]
    last_t = prompts[-1]["timestamp"] if prompts else meta["started_at"]
    models = []
    for e in entries:
        if e.get("model") and e["model"] not in models:
            models.append(e["model"])

    lines = []
    lines.append("---")
    lines.append(f"session_id: {session_id}")
    lines.append(f"date: {meta['date']}")
    lines.append(f"author: {meta['author']}")
    lines.append(f"model: {', '.join(models) if models else conf['fallback_model']}")
    lines.append(f"tool: {meta['tool']}")
    lines.append(f"project: {meta['project']}")
    lines.append(f"total_exchanges: {len(entries)}")
    lines.append(f"first_prompt_time: {first_t}")
    lines.append(f"last_prompt_time: {last_t}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Session Log — {meta['date']}")
    lines.append("")
    lines.append(
        f"Session: `{short}` | Project: `{meta['project']}` | Author: `{meta['author']}`"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    for e in entries:
        lines.append(f"[LOG_ENTRY type={e['type']} num={e['num']} session={short}]")
        lines.append(f"timestamp: {e['timestamp']}")
        lines.append(f"model: {e.get('model', conf['fallback_model'])}")
        lines.append("")
        lines.append(e["body"])
        lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_log(session_id, conf):
    meta = load_meta(session_id, conf)
    entries = read_journal(session_id)
    log_dir = pathlib.Path(conf["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / meta["filename"]).write_text(
        render(session_id, meta, entries, conf), encoding="utf-8"
    )


def next_num(entries, kind):
    return sum(1 for e in entries if e["type"] == kind) + 1


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    conf = cfg()
    session_id = payload.get("session_id") or "no-session"
    transcript = payload.get("transcript_path") or ""
    event = payload.get("hook_event_name") or ""
    model = model_from_transcript(transcript, conf["fallback_model"])

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    load_meta(session_id, conf)
    entries = read_journal(session_id)

    if event == "UserPromptSubmit":
        prompt = payload.get("prompt", "")
        if not prompt.strip():
            sys.exit(0)
        append_entry(
            session_id,
            {
                "type": "PROMPT",
                "num": next_num(entries, "PROMPT"),
                "timestamp": now_iso(),
                "model": model,
                "body": prompt,
            },
        )
        write_log(session_id, conf)

    elif event == "Stop":
        if payload.get("stop_hook_active"):
            sys.exit(0)
        body = final_response_from_transcript(transcript)
        if not body:
            sys.exit(0)
        # don't double-log if Stop fires twice for one turn
        prior = [e for e in entries if e["type"] == "RESPONSE"]
        if prior and prior[-1]["body"] == body:
            sys.exit(0)
        append_entry(
            session_id,
            {
                "type": "RESPONSE",
                "num": next_num(entries, "RESPONSE"),
                "timestamp": now_iso(),
                "model": model,
                "body": body,
            },
        )
        write_log(session_id, conf)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # a broken hook must never block the session
        sys.exit(0)
