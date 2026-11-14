import type { Metadata } from "next";

import { ComplaintDates, LetterBox } from "@/components/case-tools";
import { ComplaintHelp } from "@/components/complaint-help";

export const metadata: Metadata = {
  title: "When to go to RBI | Ritam",
  description: "The dates that matter after you complain to your bank: when it must reply, and your window for the RBI Ombudsman.",
};

export default async function ComplaintPage({
  searchParams,
}: {
  searchParams: Promise<{ problem?: string; card?: string; date?: string }>;
}) {
  const { problem, card, date } = await searchParams;
  const unsolicited = problem === "unsolicited";
  return (
    <main className="mx-auto max-w-3xl space-y-8 px-4 py-12 sm:px-6">
      <div>
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
          {unsolicited ? "A card I never asked for" : "My bank isn't solving my complaint"}
        </h1>
        <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
          {unsolicited
            ? "Don't activate it. RBI's rules say charges on a card or upgrade you never asked for must be reversed, and the bank must pay you twice their value."
            : "RBI's Ombudsman takes your complaint only after the bank has had its chance, and only within a set window. Here are your dates."}
        </p>
      </div>

      {unsolicited && (
        <LetterBox
          card={card ?? null}
          statementDate={null}
          findings={[{ rule: "rbi.unsolicited_card", charge: "A card or upgrade I never asked for" }]}
          level={2}
        />
      )}

      <section aria-labelledby="dates-title" className="space-y-4 rounded-lg border border-rule bg-surface p-5 sm:p-6">
        <h2 id="dates-title" className="text-lg font-semibold text-ink">
          Your complaint dates
        </h2>
        <ComplaintDates initial={date} />
      </section>

      <ComplaintHelp />
    </main>
  );
}
