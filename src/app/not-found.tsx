import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-[620px] flex-col justify-center px-6">
      <span className="label">404 · nothing on this frame</span>
      <h1 className="display mt-4 text-[clamp(44px,8vw,80px)] leading-[0.92]">
        Fogged.
      </h1>
      <p className="mt-5 text-[15px] leading-relaxed text-dim">
        Whatever was here did not survive the wash. If you followed a link to a
        frame, it may have only ever existed in someone else&rsquo;s browser —
        your library lives on your machine, and so does everyone else&rsquo;s.
      </p>
      <div className="mt-8 flex gap-3">
        <Link href="/" className="btn btn-primary">
          Back to the wall
        </Link>
        <Link href="/create" className="btn">
          Compose something
        </Link>
      </div>
    </div>
  );
}
