import type { Metadata } from "next";

import { StatementChecker } from "@/components/statement-checker";

export const metadata: Metadata = {
  title: "Check my bill | Ritam",
  description: "Upload your credit card bill. Ritam checks its fees, interest and GST against RBI's rules and your card's terms.",
};

export default async function StatementPage({
  searchParams,
}: {
  searchParams: Promise<{ bills?: string }>;
}) {
  const { bills } = await searchParams;
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">Check my bill</h1>
      <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
        Upload your monthly credit card statement. Ritam lists every fee, interest charge and GST amount, checks them
        against RBI&apos;s rules and your card&apos;s terms, and tells you which ones to raise with your bank.
      </p>
      <div className="mt-8">
        <StatementChecker twoBills={bills === "2"} />
      </div>
    </main>
  );
}
