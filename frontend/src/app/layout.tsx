import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, IBM_Plex_Sans, IBM_Plex_Sans_Devanagari, IBM_Plex_Serif } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});
const plexDeva = IBM_Plex_Sans_Devanagari({
  variable: "--font-plex-deva",
  subsets: ["devanagari"],
  weight: ["500"],
  display: "swap",
});
const display = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["600", "800"],
  display: "swap",
});
const plexSerif = IBM_Plex_Serif({
  variable: "--font-plex-serif",
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ritam | Banks talk. Ritam checks.",
  description:
    "Ritam reads a credit card's bank pages, terms, notices and comparison sites, and shows what's missing, conflicting or out of date, with the exact quote behind every finding.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0a0b08" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN">
      <body className={`${plexSans.variable} ${plexDeva.variable} ${plexSerif.variable} ${display.variable} font-sans`}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-neon focus:px-3 focus:py-2 focus:text-night"
        >
          Skip to content
        </a>
        <header className="border-b border-rule bg-night">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-baseline gap-2 text-ink" aria-label="Ritam home">
              <span className="font-display text-xl font-extrabold tracking-tight">Ritam</span>
              <span lang="sa" className="text-sm text-mute">
                ऋतम्
              </span>
            </Link>
            <nav aria-label="Main" className="flex items-center gap-5 text-sm font-medium text-ink">
              <Link href="/questions" className="inline-flex min-h-11 items-center underline-offset-4 hover:underline">
                Questions
              </Link>
              <Link href="/#start" className="inline-flex min-h-11 items-center underline-offset-4 hover:underline">
                Get a card report
              </Link>
            </nav>
          </div>
        </header>
        <div id="main">{children}</div>
        <footer className="mt-20 border-t border-rule bg-surface">
          <div className="mx-auto grid max-w-6xl gap-4 px-4 py-8 text-sm text-mute sm:grid-cols-2 sm:px-6">
            <p className="max-w-prose">
              Ritam shows possible issues to check. It is not financial advice and never calls anything a
              violation. Always confirm with the bank&apos;s latest official documents.
            </p>
            <p className="max-w-prose">
              What happens to your data: pages and PDFs you add are stored to show you the evidence. Names,
              card numbers, phone numbers and emails in pasted chats are masked before storage or AI
              processing.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
