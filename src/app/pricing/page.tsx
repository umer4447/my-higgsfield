"use client";

import { useEffect, useState } from "react";
import { type LedgerRow, api } from "@/lib/api";
import { useStore } from "@/lib/store";

export default function PricingPage() {
  const { me, catalog, setPlan } = useStore();
  const PLANS = catalog?.plans ?? [];
  const MODELS = catalog?.models ?? [];
  const planName = me?.planName ?? "—";

  // The ledger is paged server-side; the pricing page shows the recent tail.
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  useEffect(() => {
    if (!me) return;
    api
      .ledger({ limit: 40 })
      .then((page) => setLedger(page.data))
      .catch(() => setLedger([]));
  }, [me]);

  return (
    <div className="mx-auto max-w-[1200px] px-4 pb-32 pt-12 sm:px-6">
      <header className="max-w-[58ch]">
        <h1 className="display text-[clamp(40px,6vw,68px)] leading-[0.92]">
          Credits, and
          <br />
          what they buy.
        </h1>
        <p className="mt-5 text-[15px] leading-relaxed text-dim">
          The number that actually matters is the one nobody puts on a pricing
          page: a motion loop costs nine times a still. So here it is, first,
          before the plans.
        </p>
      </header>

      <div className="mt-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {MODELS.map((m) => (
          <div key={m.id} className="card p-3.5">
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-medium">{m.name}</span>
              <span className="flex-1" />
              <span className="mono text-[15px] text-safelight">{m.creditCost}</span>
              <span className="label">cr</span>
            </div>
            <p className="label mt-1">{m.mode === "motion" ? "motion" : "still"}</p>
          </div>
        ))}
      </div>

      <div className="sprocket my-10" />

      <div className="grid gap-4 lg:grid-cols-3">
        {PLANS.map((p) => {
          const current = me?.planId === p.id;
          return (
            <div
              key={p.id}
              className={`card relative flex flex-col p-6 ${
                p.featured ? "border-safelight/40" : ""
              }`}
            >
              {p.featured && (
                <span className="label absolute -top-2 left-6 rounded-full bg-safelight px-2 py-0.5 !text-[9px] !text-[#1a0700]">
                  most taken
                </span>
              )}
              <h2 className="display text-[30px] leading-none">{p.name}</h2>
              <p className="mt-2 text-[13px] text-dim">{p.tagline}</p>

              <div className="mt-6 flex items-baseline gap-1.5">
                <span className="mono text-[34px] leading-none">
                  {p.priceCents / 100 === 0 ? "Free" : `$${p.priceCents / 100}`}
                </span>
                {p.priceCents / 100 > 0 && <span className="label">/ month</span>}
              </div>
              <p className="mono mt-1.5 text-[12px] text-safelight">
                {p.monthlyCredits.toLocaleString()} credits
              </p>

              <ul className="mt-6 space-y-2">
                {p.perks.map((x) => (
                  <li key={x} className="flex gap-2.5 text-[13px] leading-snug text-dim">
                    <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-safelight" />
                    {x}
                  </li>
                ))}
              </ul>

              <div className="flex-1" />
              <button
                disabled={current}
                onClick={() =>
                  void setPlan(p.id)
                }
                className={`btn mt-7 w-full ${p.featured ? "btn-primary" : ""}`}
              >
                {current ? `On ${p.name}` : `Switch to ${p.name}`}
              </button>
            </div>
          );
        })}
      </div>

      <p className="mt-4 text-[12px] leading-relaxed text-faint">
        No card is taken and nothing is charged — switching a plan here credits
        your balance so you can keep using the demo. Real billing is one of the
        things deliberately left out; it would have cost a day and shown nothing
        about the product.
      </p>

      {/* ledger */}
      <div className="sprocket my-10" />
      <div className="flex items-baseline gap-3">
        <h2 className="display text-[28px]">Ledger</h2>
        <span className="label">
          {planName} · {(me?.credits ?? 0)} credits
        </span>
      </div>
      <p className="mt-2 max-w-[56ch] text-[13px] leading-relaxed text-dim">
        Every debit, itemised, including automatic refunds for frames that never
        came back. You should always be able to audit where your credits went.
      </p>

      <div className="card mt-5 overflow-hidden">
        {ledger.length === 0 ? (
          <p className="p-5 text-[13px] text-faint">Nothing spent yet.</p>
        ) : (
          ledger.map((l) => (
            <div
              key={l.id}
              className="flex items-center gap-4 border-b border-line-soft px-4 py-2.5 last:border-0"
            >
              <span className="label w-[92px] shrink-0">
                {new Date(l.createdAt).toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] text-dim">
                {l.reason}
              </span>
              <span
                className={`mono text-[13px] ${l.delta > 0 ? "text-fix" : "text-fg"}`}
              >
                {l.delta > 0 ? "+" : ""}
                {l.delta}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
