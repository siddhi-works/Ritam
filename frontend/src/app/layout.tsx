import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, IBM_Plex_Sans_Devanagari, IBM_Plex_Serif } from "next/font/google";
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

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f7f8fa" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN">
      <body className={`${plexSans.variable} ${plexDeva.variable} ${plexSerif.variable} font-sans`}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-white"
        >
          Skip to content
        </a>
        <header className="border-b border-rule bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-baseline gap-2 text-ink" aria-label="Ritam home">
              <span className="text-lg font-semibold tracking-tight">Ritam</span>
              <span lang="sa" className="text-sm text-mute">
                ऋतम्
              </span>
            </Link>
            <Link href="/#start" className="text-sm font-medium text-ink underline-offset-4 hover:underline">
              Start an audit
            </Link>
          </div>
        </header>
        <div id="main">{children}</div>
        <footer className="mt-20 border-t border-rule bg-white">
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
