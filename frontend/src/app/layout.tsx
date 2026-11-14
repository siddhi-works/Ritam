import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, IBM_Plex_Sans, IBM_Plex_Sans_Devanagari, IBM_Plex_Serif } from "next/font/google";
import Link from "next/link";

import { SiteNav } from "@/components/site-nav";

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
  title: "Ritam: check your credit card bill and terms against RBI's rules",
  description:
    "Free and independent. Check your credit card bill and your card's terms against RBI's rules, see what the bank shouldn't have charged, and get a complaint letter ready to send. Every point shows its source.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0a0b08" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" suppressHydrationWarning>
      <head>
        {/* Applies saved reading options before the page paints. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{for(const p of ["contrast","large"])if(localStorage.getItem("ritam."+p)==="1")document.documentElement.dataset[p]="1"}catch(e){}`,
          }}
        />
      </head>
      <body className={`${plexSans.variable} ${plexDeva.variable} ${plexSerif.variable} ${display.variable} font-sans`}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-neon focus:px-3 focus:py-2 focus:text-night"
        >
          Skip to content
        </a>
        <header className="border-b border-rule bg-night">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 px-4 py-3 sm:px-6">
            <Link href="/" className="inline-flex min-h-11 items-center gap-2 text-ink" aria-label="Ritam home">
              <span className="font-display text-xl font-extrabold tracking-tight text-neon">Ritam</span>
              <span lang="sa" className="text-sm text-mute">
                ऋतम्
              </span>
            </Link>
            <SiteNav />
          </div>
        </header>
        <div id="main">{children}</div>
        <footer className="mt-20 border-t border-rule bg-surface">
          <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm leading-relaxed text-mute sm:px-6 md:grid-cols-3">
            <div>
              <p className="font-semibold text-ink">About Ritam</p>
              <p className="mt-2 max-w-prose">
                Ritam is an independent, free service. It doesn&apos;t sell credit cards, show ads or take money from banks.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Your privacy</p>
              <p className="mt-2 max-w-prose">
                Bills you upload are read once and never stored. Names, addresses, card numbers, phone numbers and emails
                are hidden before any processing. Documents for card reports are kept so you can see the source.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Please note</p>
              <p className="mt-2 max-w-prose">
                Ritam points out what to check and what to ask your bank. It is not financial or legal advice. Your
                bank&apos;s latest official documents and RBI&apos;s rules are the final word.
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
