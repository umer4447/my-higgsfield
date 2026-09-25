"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Job } from "@/lib/api";
import { activeJobs, modelName, presetName, useStore } from "@/lib/store";
import Frame from "./Frame";

/**
 * The tray. Jobs keep running server-side while you browse; this is where they
 * land. Updates arrive over SSE, so nothing here polls.
 */
export default function JobTray() {
  const { jobs, catalog, cancelJob } = useStore();
  const [open, setOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  const active = activeJobs(jobs);
  const recent = jobs.slice(0, 6);

  useEffect(() => {
    if (active.length === 0) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [active.length]);

  // Open the tray when new work arrives, during render on the changed value.
  const [lastActive, setLastActive] = useState(active.length);
  if (lastActive !== active.length) {
    setLastActive(active.length);
    if (active.length > 0) setOpen(true);
  }

  if (recent.length === 0) return null;

  const frames = recent.reduce((n, j) => n + j.outputs.length, 0);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-3 pb-3">
      <div
        data-testid="job-tray"
        className="pointer-events-auto w-full max-w-[860px] overflow-hidden rounded-[14px] border border-line bg-bg/92 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl"
      >
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
        >
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
              active.length > 0 ? "bg-safelight pulse-dot" : "bg-fix"
            }`}
          />
          <span data-testid="tray-status" className="label !text-[10px] !text-fg">
            {active.length > 0
              ? `${active.length} job${active.length > 1 ? "s" : ""} developing`
              : "tray"}
          </span>
          <span className="label !text-[10px]">{frames} frames</span>
          <span className="flex-1" />
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            className={`ml-2 shrink-0 text-faint transition-transform ${open ? "" : "rotate-180"}`}
            aria-hidden
          >
            <path d="M2 8l4-4 4 4" stroke="currentColor" strokeWidth="1.4" fill="none" />
          </svg>
        </button>

        {open && (
          <div className="max-h-[42vh] overflow-y-auto border-t border-line-soft">
            {recent.map((job) => (
              <TrayRow
                key={job.id}
                job={job}
                now={now}
                modelLabel={modelName(catalog, job.modelId)}
                presetLabel={presetName(catalog, job.presetSlug)}
                onCancel={() => void cancelJob(job.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const DONE: Job["status"][] = ["succeeded", "partial", "failed", "cancelled"];

function TrayRow({
  job,
  now,
  modelLabel,
  presetLabel,
  onCancel,
}: {
  job: Job;
  now: number;
  modelLabel: string;
  presetLabel: string | null;
  onCancel: () => void;
}) {
  const ready = job.outputs.filter((o) => o.status === "ready").length;
  const age = now - new Date(job.createdAt).getTime();
  const pct = DONE.includes(job.status)
    ? 100
    : job.batch > 0 && ready > 0
      ? Math.max(8, (ready / job.batch) * 100)
      : Math.min(94, 8 + (1 - Math.exp(-age / 9000)) * 92);

  const colour =
    job.status === "failed" || job.status === "cancelled"
      ? "var(--stop)"
      : job.status === "succeeded"
        ? "var(--fix)"
        : "var(--safelight)";

  return (
    <div
      data-testid="tray-job"
      data-job-status={job.status}
      className="border-b border-line-soft px-4 py-3 last:border-0"
    >
      <div className="flex items-start gap-3">
        <div className="flex -space-x-2">
          {job.outputs.slice(0, 4).map((o) => (
            <Link
              key={o.id}
              href={`/a/${o.id}`}
              className="block h-11 w-11 shrink-0 overflow-hidden rounded-[6px] border border-line ring-1 ring-black/40"
            >
              <Frame
                asset={{
                  id: o.id,
                  mode: job.mode,
                  status: o.status,
                  prompt: job.prompt,
                  url: o.url,
                  move: job.move,
                  width: o.width,
                  height: o.height,
                }}
                rounded=""
                className="!aspect-square h-full w-full"
                play={false}
              />
            </Link>
          ))}
          {job.outputs.length === 0 && (
            <div className="h-11 w-11 rounded-[6px] border border-line bg-raised" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] text-fg">{job.prompt}</p>
          <p className="label mt-1 !text-[9px] truncate">
            {modelLabel}
            {presetLabel ? ` · ${presetLabel}` : ""} · {job.batch} out ·{" "}
            {job.creditsDebited} cr
            {job.creditsRefunded > 0 ? ` · ${job.creditsRefunded} refunded` : ""}
            {job.error ? ` · ${job.error}` : ""}
          </p>
          <div className="mt-2 h-[2px] w-full overflow-hidden rounded-full bg-line-soft">
            <div
              className="h-full rounded-full transition-[width] duration-300 ease-out"
              style={{ width: `${pct}%`, background: colour }}
            />
          </div>
        </div>

        {job.status === "queued" && (
          <button
            onClick={onCancel}
            data-testid="tray-cancel"
            className="label shrink-0 !text-[9px] hover:!text-fg"
          >
            cancel
          </button>
        )}
      </div>
    </div>
  );
}
