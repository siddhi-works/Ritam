import type { Metadata } from "next";

import { ClosureClaim } from "@/components/closure-claim";

export const metadata: Metadata = {
  title: "Card not closed | Ritam",
  description: "If your bank didn't close your credit card within 7 working days, RBI's rules say it owes you ₹500 a day.",
};

export default async function ClosurePage({
  searchParams,
}: {
  searchParams: Promise<{ card?: string; date?: string }>;
}) {
  const { card, date } = await searchParams;
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">My card wasn&apos;t closed</h1>
      <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
        RBI&apos;s rules give a bank 7 working days to close a card once you ask, if nothing is owed on it. After that it
        must pay you ₹500 for every day of delay. Ritam works out the amount and writes the claim.
      </p>
      <div className="mt-8">
        <ClosureClaim initialCard={card ?? ""} initialDate={date ?? ""} />
      </div>
    </main>
  );
}
