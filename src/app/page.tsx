import Link from "next/link";
import Wall from "@/components/Wall";
import Hero from "@/components/Hero";

export default function Home() {
  return (
    <>
      <Hero />
      <section className="mx-auto max-w-[1500px] px-4 pb-32 sm:px-6">
        <div className="mb-5 flex items-end gap-4 border-t border-line pt-6">
          <div>
            <h2 className="display text-[30px] leading-none">The Wall</h2>
            <p className="mt-1.5 max-w-[52ch] text-[13.5px] leading-relaxed text-dim">
              Everything here shows the prompt that made it. Hover a frame, read
              it, hit Remix and it loads into the composer with the same model,
              preset and seed.
            </p>
          </div>
          <span className="flex-1" />
          <Link href="/presets" className="btn hidden sm:inline-flex">
            Browse presets
          </Link>
        </div>
        <Wall />
      </section>
    </>
  );
}
