"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";

const LINKS = [
  { href: "/", label: "Wall" },
  { href: "/create", label: "Compose" },
  { href: "/presets", label: "Presets" },
  { href: "/library", label: "Contact sheet" },
];

function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="21" height="21" rx="4" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="12" cy="12" r="5.2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="12" cy="12" r="1.7" fill="var(--safelight)" />
    </svg>
  );
}

export default function Nav() {
  const path = usePathname();
  const { state, planName } = useStore();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [path]);

  const running = state.jobs.filter(
    (j) => j.status === "queued" || j.status === "running",
  ).length;

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-line bg-bg/85 backdrop-blur-xl">
      <nav className="mx-auto flex h-14 max-w-[1500px] items-center gap-2 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 pr-2 text-fg">
          <Mark />
          <span className="display text-[19px] tracking-tight">Darkroom</span>
        </Link>

        <div className="mx-1 hidden h-5 w-px bg-line sm:block" />

        <div className="hidden items-center gap-0.5 sm:flex">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`relative rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                  active ? "text-fg" : "text-dim hover:text-fg"
                }`}
              >
                {l.label}
                {active && (
                  <span className="absolute inset-x-3 -bottom-[11px] h-px bg-safelight" />
                )}
              </Link>
            );
          })}
        </div>

        <div className="flex-1" />

        {running > 0 && (
          <div className="hidden items-center gap-2 rounded-full border border-line bg-raised px-3 py-1.5 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-safelight pulse-dot" />
            <span className="label !text-[9px] !text-dim">
              {running} developing
            </span>
          </div>
        )}

        <Link
          href="/pricing"
          className="group flex items-center gap-2 rounded-full border border-line bg-raised px-3 py-1.5 transition-colors hover:border-[#33333a]"
          title={`${planName} plan`}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
            <circle cx="6" cy="6" r="5" stroke="var(--safelight)" strokeWidth="1.2" fill="none" />
            <circle cx="6" cy="6" r="1.8" fill="var(--safelight)" />
          </svg>
          <span className="mono text-[12px] font-medium">{state.credits}</span>
          <span className="label !text-[9px] hidden sm:inline">credits</span>
        </Link>

        <Link href="/create" className="btn btn-primary hidden sm:inline-flex">
          Compose
        </Link>

        <button
          className="btn btn-ghost !px-2 sm:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-label="Menu"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
            <path d="M2 5h14M2 9h14M2 13h14" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
      </nav>

      {open && (
        <div className="border-t border-line bg-bg px-4 py-2 sm:hidden">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="block rounded-md px-2 py-2.5 text-[15px] text-dim hover:text-fg"
            >
              {l.label}
            </Link>
          ))}
          <Link href="/pricing" className="block rounded-md px-2 py-2.5 text-[15px] text-dim">
            Plans
          </Link>
        </div>
      )}
    </header>
  );
}
