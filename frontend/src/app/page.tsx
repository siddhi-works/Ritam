import Link from "next/link";

import { AuditForm } from "@/components/audit-form";
import { ExampleAudits } from "@/components/example-audits";
import { HeroCards } from "@/components/hero-cards";
import { LabelTag } from "@/components/label-tag";
import { ProblemRouter } from "@/components/problem-router";
import { Specimen } from "@/components/specimen";
import { Button } from "@/components/ui/button";
import type { Label } from "@/lib/api";
import { LABELS } from "@/lib/vocab";

// The three things a person can do here, in their words.
const ACTIONS = [
  {
    href: "/statement",
    title: "Check my bill",
    body: "Upload your statement. See every fee, interest charge and GST amount, and which ones the bank shouldn't have charged.",
  },
  {
    href: "#help",
    title: "Fix a problem",
    body: "A wrong fee, a card that won't close, a payment you didn't make. Get the steps, the rule and a complaint letter ready to send.",
  },
  {
    href: "#start",
    title: "Understand a card",
    body: "Name any Indian credit card. See its real charges and benefits, what changed, and where sources disagree.",
  },
];

// Promises a person can check for themselves on every page.
const PROMISES = [
  {
    title: "Every point shows its source",
    body: "Each fact links to the exact line in the bank's own document, your bill or RBI's rules. If the line can't be found, the point is left out.",
  },
  {
    title: "Rules, not opinions",
    body: "Ritam applies RBI's published rules for credit cards and names the rule each time, so you can quote it to your bank.",
  },
  {
    title: "Honest about what's unclear",
    body: "When the evidence is mixed, Ritam says so. It points out what to ask the bank; it never claims a bank broke the law.",
  },
];

const TRUST = [
  { title: "Free", body: "No sign-up and no fees." },
  { title: "Private", body: "Bills are read once and never stored. Names and card numbers are hidden first." },
  { title: "Independent", body: "Ritam doesn't sell cards or take money from banks." },
  { title: "India only", body: "Built on RBI's rules for cards issued in India." },
];

export default function Home() {
  return (
    <main>
      <section aria-labelledby="hero-title" className="ledger relative overflow-hidden border-b border-rule">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 md:grid-cols-[1.1fr_1fr] md:py-24">
          <div>
            <h1
              id="hero-title"
              className="font-display text-[3.25rem] font-extrabold leading-[0.95] tracking-[-0.03em] text-ink sm:text-[5rem]"
            >
              Banks talk.
              <br />
              <span className="text-neon">Ritam</span> checks.
            </h1>
            <p className="mt-7 max-w-md text-lg leading-relaxed text-ink/80">
              Ritam checks your credit card bill and your card&apos;s terms against RBI&apos;s rules. It shows what&apos;s
              wrong in plain words, with proof from the bank&apos;s own documents, and writes the complaint for you.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Button asChild size="lg" className="h-12 rounded-md px-7 text-base font-semibold">
                <a href="#help">Something went wrong?</a>
              </Button>
              <Button asChild size="lg" variant="outline" className="h-12 rounded-md border-ink/45 bg-transparent px-7 text-base">
                <a href="/statement">Check my bill</a>
              </Button>
              <Button asChild size="lg" variant="outline" className="h-12 rounded-md border-ink/45 bg-transparent px-7 text-base">
                <a href="#start">Get a card report</a>
              </Button>
            </div>
            <p className="mt-4 text-sm text-mute">Free. No sign-up. Your bills are never stored.</p>
          </div>
          <HeroCards />
        </div>
      </section>

      <section id="help" aria-labelledby="help-title" className="scroll-mt-6 border-b border-rule">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1fr_1.4fr]">
          <div>
            <h2 id="help-title" className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
              Something went wrong with your card?
            </h2>
            <p className="mt-3 max-w-prose text-lg leading-relaxed text-ink/80">
              A fee you didn&apos;t expect, a card that won&apos;t close, reward points that disappeared. Describe it in your
              own words, in English or Hindi. Ritam tells you what RBI&apos;s rules say and what to do next.
            </p>
          </div>
          <ProblemRouter />
        </div>
      </section>

      <section aria-labelledby="actions-title" className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 id="actions-title" className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
            What you can do with Ritam
          </h2>
          <ul className="mt-8 grid gap-px overflow-hidden rounded-lg border border-rule bg-rule md:grid-cols-3">
            {ACTIONS.map((a) => (
              <li key={a.title} className="bg-night">
                <a href={a.href} className="group block h-full p-6 hover:bg-surface">
                  <h3 className="font-display text-2xl font-semibold text-ink group-hover:text-neon">{a.title}</h3>
                  <p className="mt-2 text-[0.9375rem] leading-relaxed text-ink/80">{a.body}</p>
                </a>
              </li>
            ))}
          </ul>
          <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4" aria-label="Why people trust Ritam">
            {TRUST.map((t) => (
              <li key={t.title}>
                <p className="font-semibold text-neon">{t.title}</p>
                <p className="mt-1 text-[0.9375rem] text-ink/80">{t.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="proof-title" className="border-b border-rule">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1fr_1.2fr]">
          <div>
            <h2 id="proof-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
              Told one thing.
              <br />
              Written another.
            </h2>
            <p className="mt-4 max-w-md text-lg text-mute">
              From a real report: what customer care said, next to what the bank wrote. The highlighted line is copied
              word for word from the bank&apos;s document.
            </p>
          </div>
          <Specimen />
        </div>
      </section>

      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <section id="start" className="scroll-mt-6 py-16" aria-labelledby="start-title">
          <h2 id="start-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
            Get your card report
          </h2>
          <p className="mb-10 mt-3 max-w-prose text-lg text-mute">
            Name the card and what you want to know. Ritam reads the bank&apos;s documents for you, usually in 2 to 5
            minutes.
          </p>
          <AuditForm />
        </section>

        <section id="examples" className="scroll-mt-6 border-t border-rule py-16" aria-labelledby="examples-title">
          <h2 id="examples-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
            See a sample report
          </h2>
          <p className="mb-8 mt-3 max-w-prose text-lg text-mute">
            Real reports built from Axis Bank, HDFC Bank and ICICI Bank documents. Open one to see what you get.
          </p>
          <ExampleAudits />
        </section>

        <section className="border-t border-rule py-16" aria-labelledby="how-title">
          <h2 id="how-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
            Why you can rely on it
          </h2>
          <ul className="mt-10 grid gap-px overflow-hidden rounded-lg border border-rule bg-rule md:grid-cols-3">
            {PROMISES.map((s) => (
              <li key={s.title} className="bg-night p-6">
                <h3 className="font-display text-2xl font-semibold leading-tight text-ink">{s.title}</h3>
                <p className="mt-3 text-[0.9375rem] leading-relaxed text-ink/75">{s.body}</p>
              </li>
            ))}
          </ul>

          <h3 className="mt-14 font-display text-2xl font-semibold text-ink">What the labels on each point mean</h3>
          <dl className="mt-5 grid gap-6 md:grid-cols-3">
            {(Object.keys(LABELS) as Label[]).map((k) => (
              <div key={k}>
                <dt>
                  <LabelTag label={k} />
                </dt>
                <dd className="mt-2 text-[0.9375rem] text-ink/75">{LABELS[k].meaning}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-10 text-[0.9375rem] text-mute">
            Have a general question about credit cards?{" "}
            <Link href="/questions" className="text-ink underline underline-offset-4 hover:text-neon">
              Read the answers
            </Link>
            .
          </p>
        </section>
      </div>
    </main>
  );
}
