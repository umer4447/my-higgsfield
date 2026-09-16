import Link from "next/link";

export default function Footer() {
  return (
    <footer className="mt-20 border-t border-line">
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-start gap-x-12 gap-y-6 px-4 py-10 sm:px-6">
        <div className="max-w-[40ch]">
          <div className="display text-[20px]">Darkroom</div>
          <p className="mt-2 text-[12.5px] leading-relaxed text-faint">
            A rebuild of higgsfield.ai, done as a build exercise. Not affiliated
            with it. Stills are really generated; the camera move on a motion
            result is rendered in your browser, and the result page says so.
          </p>
        </div>

        <nav className="flex flex-col gap-1.5">
          <span className="label mb-1">product</span>
          {[
            ["/", "The Wall"],
            ["/create", "Compose"],
            ["/presets", "Presets"],
            ["/library", "Contact sheet"],
            ["/pricing", "Credits"],
          ].map(([h, l]) => (
            <Link key={h} href={h} className="text-[12.5px] text-dim hover:text-fg">
              {l}
            </Link>
          ))}
        </nav>

        <div className="max-w-[34ch]">
          <span className="label">credits</span>
          <p className="mt-2.5 text-[12.5px] leading-relaxed text-faint">
            Image generation by{" "}
            <a
              href="https://pollinations.ai"
              target="_blank"
              rel="noreferrer noopener"
              className="text-dim underline underline-offset-2 hover:text-fg"
            >
              Pollinations
            </a>
            , whose mark appears on the frames. Chosen so this link works for
            anyone who opens it, with no key and no sign-up.
          </p>
        </div>
      </div>
    </footer>
  );
}
