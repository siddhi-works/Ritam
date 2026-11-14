import type { Metadata } from "next";

import { CardFinder } from "@/components/card-finder";

export const metadata: Metadata = {
  title: "Card finder (Beta) | Ritam",
  description: "Tell Ritam how you spend. It shows what to look for in a credit card, with the maths in your own rupees.",
};

export default function CardFinderPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <p className="inline-flex rounded-full border border-neon/60 px-3 py-1 text-sm font-medium text-neon">Beta</p>
      <h1 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
        What card should I look for?
      </h1>
      <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
        Tell Ritam roughly how you spend. It shows what features would actually pay off for you, and what to avoid,
        worked out in your own rupees. Ritam doesn&apos;t recommend or sell any card, so the advice isn&apos;t tilted
        towards one.
      </p>
      <div className="mt-8">
        <CardFinder />
      </div>
    </main>
  );
}
