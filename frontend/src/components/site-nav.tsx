"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ReadingControls } from "@/components/assist";

const LINKS = [
  { href: "/#help", label: "Get help" },
  { href: "/statement", label: "Check my bill" },
  { href: "/#start", label: "Get a card report" },
  { href: "/card-finder", label: "Card finder" },
  { href: "/questions", label: "Questions" },
];

const LINK = "inline-flex min-h-11 items-center underline-offset-4 hover:underline";

/** Full navigation on wider screens; on phones, "Get help" plus a menu, so the header stays one
 * short row even with larger text. */
export function SiteNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => setOpen(false), [pathname]);

  return (
    <>
      <nav aria-label="Main" className="hidden items-center gap-x-5 text-sm font-medium text-ink md:flex">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={LINK}>
            {l.label}
          </Link>
        ))}
        <ReadingControls />
      </nav>

      <div className="flex items-center gap-1 md:hidden">
        <Link href="/#help" className={`${LINK} px-2 text-sm font-semibold text-neon`}>
          Get help
        </Link>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 text-sm text-ink"
        >
          {open ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
          Menu
        </button>
      </div>
      {open && (
        <nav
          id="mobile-menu"
          aria-label="Main"
          className="basis-full space-y-1 border-t border-rule pb-2 pt-2 text-[0.9375rem] font-medium text-ink md:hidden"
        >
          {LINKS.slice(1).map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className={`${LINK} w-full`}>
              {l.label}
            </Link>
          ))}
          <div className="pt-1">
            <ReadingControls labelled />
          </div>
        </nav>
      )}
    </>
  );
}
