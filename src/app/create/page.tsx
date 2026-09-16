import { Suspense } from "react";
import Composer from "@/components/Composer";

export const metadata = { title: "Compose — Darkroom" };

export default function CreatePage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1500px] px-6 py-16">
          <div className="label">loading composer…</div>
        </div>
      }
    >
      <Composer />
    </Suspense>
  );
}
