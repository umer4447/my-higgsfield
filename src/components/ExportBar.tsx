"use client";

import { useState } from "react";
import type { Asset } from "@/lib/api";

/**
 * Downloads.
 *
 * Stills come down as a PNG. Motion is rendered to a real .webm in the browser:
 * the generated keyframe is drawn to a canvas under the same camera move you see
 * on screen, captured with MediaRecorder, and saved. No server, no render farm,
 * and the file you get is the thing you were looking at.
 */

type Move = string;
type Tf = { s: number; x: number; y: number; r: number; blur: number };

const EASE = (t: number) => 0.5 - Math.cos(Math.PI * t) / 2;
/** ping-pong so the loop is seamless */
const PP = (t: number) => (t < 0.5 ? t * 2 : (1 - t) * 2);

const MOVES: Record<Move, (t: number) => Tf> = {
  push: (t) => ({ s: 1.02 + 0.2 * EASE(PP(t)), x: 0, y: 0, r: 0, blur: 0 }),
  pull: (t) => ({ s: 1.24 - 0.22 * EASE(PP(t)), x: 0, y: 0, r: 0, blur: 0 }),
  orbit: (t) => {
    const e = EASE(PP(t));
    return { s: 1.22, x: -0.03 + 0.06 * e, y: 0.01 - 0.02 * e, r: -0.8 + 1.6 * e, blur: 0 };
  },
  whip: (t) => {
    const p = PP(t);
    const e = EASE(p);
    return { s: 1.3, x: -0.07 + 0.14 * e, y: 0, r: 0, blur: 6 * Math.sin(Math.PI * p) };
  },
  crane: (t) => {
    const e = EASE(PP(t));
    return { s: 1.24 - 0.18 * e, x: 0, y: 0.06 - 0.1 * e, r: 0, blur: 0 };
  },
  float: (t) => {
    const a = t * Math.PI * 2;
    return {
      s: 1.12 + 0.02 * Math.sin(a),
      x: 0.015 * Math.sin(a),
      y: -0.015 * Math.cos(a * 1.3),
      r: 0,
      blur: 0,
    };
  },
  shake: (t) => {
    const n = Math.floor(t * 18);
    const j = (k: number) => ((Math.sin(k * 127.1) * 43758.5453) % 1) * 2 - 1;
    return { s: 1.16, x: 0.012 * j(n), y: 0.01 * j(n + 7), r: 0, blur: 0 };
  },
  dolly: (t) => ({ s: 1.18, x: -0.05 + 0.1 * EASE(PP(t)), y: 0, r: 0, blur: 0 }),
};

/**
 * `asset.url` is null until the frame is READY, and every handler here needs it.
 * Guarding once in a wrapper gives the body a non-null `src` rather than a
 * null check in each function.
 */
export default function ExportBar({ asset }: { asset: Asset }) {
  if (!asset.url) return null;
  return <ReadyExportBar asset={asset} src={asset.url} />;
}

function ReadyExportBar({ asset, src }: { asset: Asset; src: string }) {
  const [busy, setBusy] = useState<null | string>(null);
  const [note, setNote] = useState<string | null>(null);

  async function loadImage(): Promise<HTMLImageElement> {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.src = src;
    await img.decode();
    return img;
  }

  async function downloadStill() {
    setBusy("still");
    setNote(null);
    try {
      const res = await fetch(src);
      const blob = await res.blob();
      save(blob, `darkroom-${asset.seed}.jpg`);
    } catch {
      window.open(src, "_blank");
    } finally {
      setBusy(null);
    }
  }

  async function exportMotion() {
    setBusy("motion");
    setNote(null);
    try {
      const img = await loadImage();
      const W = Math.min(960, asset.width);
      const H = Math.round((W * asset.height) / asset.width);
      const canvas = document.createElement("canvas");
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext("2d")!;

      const stream = canvas.captureStream(30);
      const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
        ? "video/webm;codecs=vp9"
        : "video/webm";
      const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6_000_000 });
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

      const done = new Promise<void>((r) => (rec.onstop = () => r()));
      rec.start();

      const fn = MOVES[asset.move ?? "push"];
      const DURATION = 5000;
      const t0 = performance.now();

      await new Promise<void>((resolve) => {
        function draw(now: number) {
          const t = Math.min(1, (now - t0) / DURATION);
          const tf = fn(t);
          ctx.clearRect(0, 0, W, H);
          ctx.save();
          ctx.filter = tf.blur ? `blur(${tf.blur}px)` : "none";
          ctx.translate(W / 2 + tf.x * W, H / 2 + tf.y * H);
          ctx.rotate((tf.r * Math.PI) / 180);
          ctx.scale(tf.s, tf.s);
          ctx.drawImage(img, -W / 2, -H / 2, W, H);
          ctx.restore();
          if (t < 1) requestAnimationFrame(draw);
          else resolve();
        }
        requestAnimationFrame(draw);
      });

      rec.stop();
      await done;
      save(new Blob(chunks, { type: "video/webm" }), `darkroom-${asset.seed}.webm`);
    } catch {
      setNote(
        "The browser would not let the canvas read that frame. Download the still instead.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={downloadStill} disabled={!!busy} className="btn !h-8 !px-3 !text-[12px]">
          {busy === "still" ? "saving…" : "Download frame"}
        </button>
        {asset.mode === "motion" && (
          <button
            onClick={exportMotion}
            disabled={!!busy}
            className="btn !h-8 !px-3 !text-[12px]"
          >
            {busy === "motion" ? "rendering 5s…" : "Export .webm"}
          </button>
        )}
        <span className="flex-1" />
        <span className="label">{asset.ratioId}</span>
      </div>
      {note && <p className="mt-2 text-[11.5px] text-stop">{note}</p>}
    </div>
  );
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
