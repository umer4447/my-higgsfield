import type { Metadata } from "next";
import localFont from "next/font/local";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { StoreProvider } from "@/lib/store";
import { JobRunner } from "@/lib/jobs";
import Nav from "@/components/Nav";
import JobTray from "@/components/JobTray";

/* self-hosted: no runtime call to a font CDN, nothing to block, no layout shift */
const display = localFont({
  variable: "--font-display",
  display: "swap",
  src: [
    { path: "../fonts/instrument-serif-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../fonts/instrument-serif-latin-400-italic.woff2", weight: "400", style: "italic" },
  ],
});

export const metadata: Metadata = {
  title: "Darkroom — an AI-native creative suite",
  description:
    "Prompt to frame to motion, in one composer. Every image on the wall shows its prompt and can be remixed.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${GeistSans.variable} ${GeistMono.variable}`}>
        <StoreProvider>
          <JobRunner />
          <Nav />
          <main className="pt-[57px]">{children}</main>
          <JobTray />
        </StoreProvider>
      </body>
    </html>
  );
}
