"use client";

import { Printer } from "lucide-react";

import { LinkOut } from "@/components/link-out";
import { CYBERCRIME, RBI_COMPLAINT } from "@/lib/questions";

/** What to do when a charge or term looks wrong, in the order RBI expects. */
export function ComplaintHelp() {
  return (
    <section aria-labelledby="complain-title" className="rounded-lg border border-rule bg-surface p-5 sm:p-6">
      <h2 id="complain-title" className="text-lg font-semibold text-ink">
        If something looks wrong
      </h2>
      <ol className="mt-3 list-decimal space-y-2.5 pl-5 text-[0.9375rem] leading-relaxed text-ink/85 marker:text-mute">
        <li>
          Write to your bank first, by email or its complaint form, and keep the complaint number. Attach this report or the
          bill, and quote the bank&apos;s own terms.
        </li>
        <li>
          If the bank doesn&apos;t reply within 30 days, or you aren&apos;t happy with the reply, complain to the{" "}
          <LinkOut href={RBI_COMPLAINT.href} className="hover:text-neon">
            RBI Ombudsman
          </LinkOut> within 90 days. It is free, and you can also call RBI on
          14448.
        </li>
        <li>
          For a payment you didn&apos;t make, tell your bank at once: reporting within 3 working days limits what you can
          lose. If it was fraud, call 1930 or report it at <LinkOut href={CYBERCRIME.href} className="hover:text-neon">
            cybercrime.gov.in
          </LinkOut>.
        </li>
      </ol>
    </section>
  );
}

/** Opens the print dialog, where "Save as PDF" gives a copy to keep or attach to a complaint. */
export function SavePdfButton() {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className="inline-flex min-h-11 items-center gap-2 rounded-md border border-ink/45 px-4 text-sm font-medium text-ink hover:border-neon print:hidden"
    >
      <Printer aria-hidden className="size-4" />
      Save as PDF or print
    </button>
  );
}
