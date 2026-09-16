# .agent-logs

The raw prompt-and-response record for this build, captured automatically by
`UserPromptSubmit` and `Stop` hooks. Setup, mechanism and the dead ends are in
[`../CAPTURE-TEST.md`](../CAPTURE-TEST.md).

Nothing in the `.md` files has been edited, tidied or reordered after the fact.
This file is an index, added so a reader can find the interesting moments
without reading everything. Timestamps below are copied from the entries; the
entries themselves are UTC, per the format spec.

## Timeline

Everything happened in one sitting on **2026-09-16**.

| UTC | ET | |
|---|---|---|
| 16:38 | 12:38 | first prompt — the assignment |
| 17:11 | 13:11 | capture verified, first commit |
| 17:18 | 13:18 | recon of higgsfield.ai committed |
| 17:54 | 13:54 | the product, first working build |
| 18:11 | 14:11 | command palette, mobile, 404 |
| 18:48 | 14:48 | handed over for local testing |
| 19:02 | 15:02 | first attempt at the frame bug |
| 19:25 | 15:25 | second attempt — the real diagnosis |
| 19:48 | 15:48 | serverless budget fix, feature-complete |

**3 hours 10 minutes**, 20 commits. `git log --reverse --date=iso` is the
receipt.

## Worth reading

**`2026-09-16_17-09-55_2e10ceaf.md` — the canary that was refused.**
Two lines long. The second capture-verification session read
`CAPTURE TEST — 8x assignment, umer4447. Reply with exactly: ...` as a prompt
injection and refused to comply. It is left in because it is a real response to
a real prompt, and because a log that only contains successes is not evidence of
anything.

**16:38 → 17:11 — reading the brief was the first bug.**
The capture-setup page renders its body in a cross-origin iframe. `WebFetch`
returned meta tags only, `textContent` came back empty, the page ignored scroll
events, and clicking its copy button froze the renderer for 45 seconds. What
worked was styling the iframe from the parent — `transform: scale(0.35)
translateY(...)` at 9000px tall — to render the whole document into one viewport
and read it in zoomed tiles. Written up in `CAPTURE-TEST.md` §5.

**17:09 — hooks do not fire in the session that installs them.**
Claude Code reads settings at process start. Both canaries landed because one
was a fresh process; the session that registered the hooks kept running with the
old config. `tools/backfill_capture.py` closes that one gap by reading the same
transcript with the same extractor. It is not a substitute for the hook and it
says so.

**18:58 → 19:25 — the same bug diagnosed wrong twice, then right.**
The wall filled with "frame lost". First diagnosis: a request stampede. A global
queue with backoff was built and verified against a stub — and changed nothing,
because the diagnosis was wrong. Second attempt started by reading the actual
network log out of a real browser instead of reasoning about it: every failure
was **HTTP 503**, and the same URL 503'd on all four retries while others
returned 200 throughout. That is a per-IP rate limit, which no amount of
client-side concurrency control can fix. The real remedy was a server-side proxy
with pacing and permanent caching, plus baking the seed wall so identical
content is not regenerated per visitor.

Both wrong turns are still in the log, and so is the commit that shipped the
first one. That sequence is the most useful thing in this directory.

**19:48 — a fix that only shows up in production.**
The proxy's retry loop could outrun the serverless `maxDuration` and hand the
platform a hard timeout instead of a response. Caught by reasoning about the
deploy target rather than by anything failing locally.

## What is in here

| File | |
|---|---|
| `2026-09-16_17-09-31_8ae96fef.md` | the build session |
| `2026-09-16_17-09-55_2e10ceaf.md` | the second capture canary |
