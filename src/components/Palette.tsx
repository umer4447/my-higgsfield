"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";

type Item = {
  id: string;
  label: string;
  hint: string;
  group: string;
  run: () => void;
};

/** ⌘K. Go anywhere, or start a shot from a preset without touching the mouse. */
export default function Palette() {
  const router = useRouter();
  const { catalog } = useStore();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const items: Item[] = useMemo(() => {
    const MODELS = catalog?.models ?? [];
    const PRESETS = catalog?.presets ?? [];
    const go = (href: string) => () => {
      setOpen(false);
      router.push(href);
    };
    return [
      { id: "n-wall", label: "The Wall", hint: "everyone's frames", group: "Go", run: go("/") },
      { id: "n-create", label: "Compose", hint: "new shot", group: "Go", run: go("/create") },
      { id: "n-presets", label: "Presets", hint: "all 18", group: "Go", run: go("/presets") },
      { id: "n-lib", label: "Contact sheet", hint: "your frames", group: "Go", run: go("/library") },
      { id: "n-price", label: "Credits & ledger", hint: "what you spent", group: "Go", run: go("/pricing") },
      ...MODELS.map((m) => ({
        id: `m-${m.id}`,
        label: `Compose with ${m.name}`,
        hint: `${m.creditCost} cr · ${m.mode === "motion" ? "motion" : "still"}`,
        group: "Model",
        run: go(`/create?model=${m.id}`),
      })),
      ...PRESETS.map((p) => ({
        id: `p-${p.slug}`,
        label: p.name,
        hint: `${p.family}${p.move ? ` · ${p.move}` : ""} — ${p.description}`,
        group: "Preset",
        run: go(
          `/create?preset=${p.slug}&model=${p.mode === "motion" ? "reel-9" : "halide-2"}`,
        ),
      })),
    ];
  }, [router, catalog]);

  const hits = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return items.slice(0, 9);
    return items
      .filter((i) => (i.label + " " + i.hint + " " + i.group).toLowerCase().includes(t))
      .slice(0, 12);
  }, [q, items]);

  // Reset the highlighted row when the query changes, during render rather
  // than in an effect, so the list never paints with a stale selection.
  const [lastQ, setLastQ] = useState(q);
  if (lastQ !== q) {
    setLastQ(q);
    setSel(0);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        setQ("");
      }
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 30);
  }, [open]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-i="${sel}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/65 px-4 pt-[14vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-[560px] overflow-hidden rounded-[14px] border border-line bg-bg shadow-[0_30px_80px_-20px_rgba(0,0,0,0.95)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line px-4">
          <span className="label">⌘K</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(s + 1, hits.length - 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(s - 1, 0));
              }
              if (e.key === "Enter") {
                e.preventDefault();
                hits[sel]?.run();
              }
            }}
            placeholder="Jump somewhere, or start from a preset…"
            className="h-12 w-full bg-transparent text-[14px] placeholder:text-faint focus:outline-none"
          />
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-1.5">
          {hits.length === 0 && (
            <p className="px-3 py-6 text-center text-[13px] text-faint">
              Nothing matches that.
            </p>
          )}
          {hits.map((h, i) => (
            <button
              key={h.id}
              data-i={i}
              onMouseEnter={() => setSel(i)}
              onClick={h.run}
              className={`flex w-full items-baseline gap-3 rounded-[8px] px-3 py-2.5 text-left transition-colors ${
                i === sel ? "bg-[#1b1b20]" : ""
              }`}
            >
              <span className="label w-[52px] shrink-0">{h.group}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] text-fg">{h.label}</span>
                <span className="mt-0.5 block truncate text-[11.5px] text-faint">
                  {h.hint}
                </span>
              </span>
              {i === sel && <span className="label shrink-0">↵</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
