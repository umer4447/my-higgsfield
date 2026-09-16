"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useStore, modelName } from "@/lib/store";
import { presetBySlug } from "@/lib/catalog";
import Frame from "@/components/Frame";

export default function LibraryPage() {
  const { state, dispatch } = useStore();
  const [kind, setKind] = useState<"all" | "image" | "motion">("all");
  const [onlyPublished, setOnlyPublished] = useState(false);
  const [q, setQ] = useState("");

  const items = useMemo(() => {
    return state.assets
      .filter((a) => (kind === "all" ? true : a.kind === kind))
      .filter((a) => (onlyPublished ? a.published : true))
      .filter((a) =>
        q.trim() ? a.prompt.toLowerCase().includes(q.trim().toLowerCase()) : true,
      );
  }, [state.assets, kind, onlyPublished, q]);

  const spent = state.ledger
    .filter((l) => l.delta < 0)
    .reduce((n, l) => n + Math.abs(l.delta), 0);

  if (!state.ready) return null;

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-32 pt-10 sm:px-6">
      <header className="flex flex-wrap items-end gap-6 border-b border-line pb-6">
        <div>
          <h1 className="display text-[clamp(38px,5vw,56px)] leading-none">
            Contact sheet
          </h1>
          <p className="mt-2 max-w-[54ch] text-[13.5px] leading-relaxed text-dim">
            Everything you have developed in this browser. Nothing here has left
            your machine.
          </p>
        </div>
        <span className="flex-1" />
        <div className="flex gap-8">
          <Stat k={state.assets.length} v="frames" />
          <Stat k={state.assets.filter((a) => a.published).length} v="on the wall" />
          <Stat k={spent} v="credits spent" />
        </div>
      </header>

      {state.assets.length === 0 ? (
        <div className="flex min-h-[46vh] flex-col items-center justify-center text-center">
          <p className="display text-[34px] leading-tight">Empty sheet.</p>
          <p className="mt-2 max-w-[42ch] text-[14px] text-dim">
            You have {state.credits} credits sitting there. A still costs two.
          </p>
          <Link href="/create" className="btn btn-primary mt-6">
            Compose something
          </Link>
        </div>
      ) : (
        <>
          <div className="my-5 flex flex-wrap items-center gap-2">
            <div className="flex gap-1">
              {(["all", "image", "motion"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setKind(f)}
                  className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                    kind === f
                      ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                      : "border-line text-faint hover:text-dim"
                  }`}
                >
                  {f === "all" ? "Everything" : f === "image" ? "Stills" : "Motion"}
                </button>
              ))}
            </div>
            <button
              onClick={() => setOnlyPublished((v) => !v)}
              className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                onlyPublished
                  ? "border-safelight text-safelight"
                  : "border-line text-faint hover:text-dim"
              }`}
            >
              Published only
            </button>
            <span className="flex-1" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search prompts"
              className="field h-8 w-[200px] px-3 text-[12.5px] placeholder:text-faint focus:outline-none"
            />
          </div>

          <div className="[column-fill:_balance] columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5">
            {items.map((a, i) => {
              const preset = a.presetSlug ? presetBySlug(a.presetSlug) : null;
              return (
                <div
                  key={a.id}
                  className="group mb-3 break-inside-avoid rise"
                  style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}
                >
                  <Link href={`/a/${a.id}`}>
                    <Frame asset={a} priority={i < 4} />
                  </Link>
                  <div className="mt-1.5 flex items-center gap-2 px-0.5">
                    <span className="label truncate">
                      {modelName(a.modelId)}
                      {preset ? ` · ${preset.name}` : ""}
                    </span>
                    <span className="flex-1" />
                    <button
                      onClick={() =>
                        dispatch({
                          t: "asset:patch",
                          id: a.id,
                          patch: { published: !a.published },
                        })
                      }
                      className={`label hover:!text-fg ${a.published ? "!text-safelight" : ""}`}
                    >
                      {a.published ? "public" : "publish"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ k, v }: { k: number; v: string }) {
  return (
    <div>
      <div className="mono text-[22px] leading-none">{k.toLocaleString()}</div>
      <div className="label mt-1.5">{v}</div>
    </div>
  );
}
