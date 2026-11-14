import type { Metadata } from "next";

import { CardChanges } from "@/components/card-changes";

export const metadata: Metadata = {
  title: "What changed on my card | Ritam",
  description: "Your card's charges and benefits when you got it, next to today's, from the bank's own documents.",
};

export default async function ChangesPage({
  searchParams,
}: {
  searchParams: Promise<{ card?: string; since?: string }>;
}) {
  const { card, since } = await searchParams;
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
        What changed on my card?
      </h1>
      <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
        Banks cut rewards, lounge visits and waivers over time. Pick your card and when you got it: Ritam shows its terms
        then and now, from the bank&apos;s own documents. RBI&apos;s rules require one month&apos;s notice before charges change.
      </p>
      <div className="mt-8">
        <CardChanges initialCard={card ?? ""} initialSince={since ?? ""} />
      </div>
    </main>
  );
}
