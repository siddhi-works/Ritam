import { ChevronDown, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ASK_THE_BANK, QUESTION_GROUPS, type QuestionLink } from "@/lib/questions";

export const metadata: Metadata = {
  title: "Credit card questions | Ritam",
  description: "Plain answers to common credit card questions, with the RBI rules and where to go next.",
};

function LinkOut({ link }: { link: QuestionLink }) {
  const internal = link.href.startsWith("/");
  if (internal)
    return (
      <Link href={link.href} className="font-medium text-ink underline underline-offset-4 hover:no-underline">
        {link.label}
      </Link>
    );
  return (
    <a
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-ink underline underline-offset-4 hover:no-underline"
    >
      {link.label}
      <ExternalLink aria-hidden className="size-3.5" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

export default function QuestionsPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Credit card questions</h1>
      <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
        Short answers to what people ask most, based on RBI&apos;s rules for card issuers. For anything about your
        own card, Ritam can check the bank&apos;s documents for you.
      </p>

      <nav aria-label="Topics" className="mt-8 flex flex-wrap gap-2">
        {QUESTION_GROUPS.map((g) => (
          <a
            key={g.title}
            href={`#${slug(g.title)}`}
            className="rounded-full border border-rule bg-white px-3 py-1.5 text-sm text-ink hover:border-ink"
          >
            {g.title}
          </a>
        ))}
      </nav>

      {QUESTION_GROUPS.map((g) => (
        <section key={g.title} id={slug(g.title)} aria-labelledby={`${slug(g.title)}-h`} className="mt-12 scroll-mt-6">
          <h2 id={`${slug(g.title)}-h`} className="text-xl font-semibold text-ink">
            {g.title}
          </h2>
          <div className="mt-4 divide-y divide-rule rounded-lg border border-rule bg-white">
            {g.questions.map((item) => (
              <details key={item.q} className="group">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 text-[1.0625rem] font-medium text-ink hover:bg-paper [&::-webkit-details-marker]:hidden">
                  {item.q}
                  <ChevronDown aria-hidden className="size-5 shrink-0 text-mute transition-transform group-open:rotate-180" />
                </summary>
                <div className="space-y-3 px-5 pb-5 text-[0.9375rem] leading-relaxed text-ink/85">
                  {item.a.map((p) => (
                    <p key={p}>{p}</p>
                  ))}
                  {item.links.length > 0 && (
                    <p className="flex flex-wrap gap-x-5 gap-y-2 pt-1 text-sm">
                      {item.links.map((l) => (
                        <LinkOut key={l.href + l.label} link={l} />
                      ))}
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        </section>
      ))}

      <section aria-labelledby="ask-bank" className="mt-12 rounded-lg border border-ink bg-white p-5 sm:p-6">
        <h2 id="ask-bank" className="text-lg font-semibold text-ink">
          Only your bank can answer
        </h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-[0.9375rem] text-ink/85">
          {ASK_THE_BANK.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-mute">
          Use the bank&apos;s app or customer care. If they don&apos;t resolve a complaint within 30 days, you can go to the{" "}
          <LinkOut link={{ label: "RBI complaint portal", href: "https://cms.rbi.org.in/" }} />.
        </p>
      </section>
    </main>
  );
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
