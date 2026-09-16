#!/usr/bin/env python3
"""
Backfill the capture log for a session that was already running when the hooks
were installed.

Claude Code loads its settings at process start, so the hooks registered
mid-session in `~/.claude/settings.json` do not fire for the session that
registered them -- they fire from the next session onwards (proven by the two
canaries in CAPTURE-TEST.md). This script closes that one gap.

It is not a substitute for the hook and it does not invent anything. It reads the
exact same session transcript the `Stop` hook reads, runs the exact same
extractor, and writes the exact same journal and markdown. The only difference is
that it is pulled rather than pushed, and it uses the transcript's own record
timestamps instead of hook-fire time -- which is slightly more accurate.

Usage:
    python3 tools/backfill_capture.py <session-id> [transcript.jsonl]
"""

import json
import re
import sys
import pathlib
import importlib.util

HOOK = pathlib.Path("/root/.claude/hooks/agent_capture.py")
spec = importlib.util.spec_from_file_location("agent_capture", HOOK)
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)

SKIP_PREFIXES = (
    "<system-reminder>",
    "Continue from where you left off",
    "[Request interrupted",
)


# The harness appends its own blocks to a user turn: session reminders, and
# "Note: <path> changed on disk" notices that quote file diffs. Those are not
# what the person typed, and when the changed file is the log itself the log
# starts quoting itself. Strip them so a PROMPT entry is the person's words,
# verbatim and in full -- which is the point.
NOISE_BLOCKS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(
        r"\nNote: [^\n]*? changed on disk since you last read it\..*$",
        re.S,
    ),
    re.compile(r"\nThe user sent a new message while you were working:.*$", re.S),
]


def strip_harness_blocks(text):
    for rx in NOISE_BLOCKS:
        text = rx.sub("", text)
    return text.strip()


def is_harness_noise(text):
    t = text.strip()
    if not t:
        return True
    return t.startswith(SKIP_PREFIXES)


def ask_tool_ids(records):
    """tool_use ids that belong to AskUserQuestion, so its results can be told
    apart from ordinary tool output that merely quotes the log."""
    ids = set()
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if (
                isinstance(b, dict)
                and b.get("type") == "tool_use"
                and b.get("name") == "AskUserQuestion"
                and b.get("id")
            ):
                ids.add(b["id"])
    return ids


def blob_text(blob):
    if isinstance(blob, list):
        return " ".join(
            x.get("text", "") for x in blob if isinstance(x, dict)
        )
    return blob if isinstance(blob, str) else ""


MID_TURN = re.compile(
    r"The user sent a new message while you were working:\s*\n(.*?)"
    r"(?:\n\nThis is how Claude Code surfaces|\Z)",
    re.S,
)
ANSWERED = re.compile(
    r"(The user answered:.*?)"
    r"(?:\n\s*(?:Read the answers carefully|You can now continue)|\Z)",
    re.S,
)


def human_turns(records):
    """(index, timestamp, prompt_text) for every turn a person actually drove."""
    asks = ask_tool_ids(records)
    out = []
    for i, rec in enumerate(records):
        if rec.get("type") != "user":
            continue
        content = (rec.get("message") or {}).get("content")
        text = None

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            if parts:
                text = "\n".join(parts)
            else:
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    blob = blob_text(b.get("content"))
                    # a message typed mid-turn is relayed through tool output
                    mid = MID_TURN.search(blob)
                    if mid:
                        text = mid.group(1).strip()
                        break
                    # AskUserQuestion answers are the person's own words, but only
                    # when the result actually belongs to an AskUserQuestion call
                    if b.get("tool_use_id") in asks:
                        ans = ANSWERED.search(blob)
                        if ans:
                            text = "[answer to AskUserQuestion] " + ans.group(1).strip()
                            break

        if text is None:
            continue
        text = strip_harness_blocks(text)
        if is_harness_noise(text):
            continue
        out.append((i, rec.get("timestamp"), text))
    return out


def assistant_text_between(records, start, end):
    chunks = []
    for rec in records[start + 1 : end]:
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    if block.get("text", "").strip():
                        chunks.append(block["text"])
    return "\n\n".join(chunks).strip()


def assistant_model_between(records, start, end, fallback):
    model = fallback
    for rec in records[start + 1 : end]:
        if rec.get("type") == "assistant":
            m = (rec.get("message") or {}).get("model")
            if m:
                model = m
    return model


def last_ts_between(records, start, end, fallback):
    ts = fallback
    for rec in records[start + 1 : end]:
        if rec.get("type") == "assistant" and rec.get("timestamp"):
            ts = rec["timestamp"]
    return ts


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    session_id = sys.argv[1]
    if len(sys.argv) > 2:
        transcript = sys.argv[2]
    else:
        transcript = f"/root/.claude/projects/-home-claude/{session_id}.jsonl"

    conf = ac.cfg()
    records = []
    with open(transcript, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    turns = human_turns(records)
    entries = []
    pnum = rnum = 0
    for k, (idx, ts, prompt) in enumerate(turns):
        end = turns[k + 1][0] if k + 1 < len(turns) else len(records)
        model = assistant_model_between(records, idx, end, conf["fallback_model"])
        pnum += 1
        entries.append(
            {
                "type": "PROMPT",
                "num": pnum,
                "timestamp": ts or ac.now_iso(),
                "model": model,
                "body": prompt,
            }
        )
        body = assistant_text_between(records, idx, end)
        if body:
            rnum += 1
            entries.append(
                {
                    "type": "RESPONSE",
                    "num": rnum,
                    "timestamp": last_ts_between(records, idx, end, ts or ac.now_iso()),
                    "model": model,
                    "body": body,
                }
            )

    ac.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ac.journal_path(session_id), "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    ac.write_log(session_id, conf)

    meta = ac.load_meta(session_id, conf)
    print(f"{len(entries)} entries -> {conf['log_dir']}/{meta['filename']}")


if __name__ == "__main__":
    main()
