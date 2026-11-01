import Link from "next/link";

import { AuditForm } from "@/components/audit-form";
import { ExampleAudits } from "@/components/example-audits";
import { HeroCards } from "@/components/hero-cards";
import { LabelTag } from "@/components/label-tag";
import { Specimen } from "@/components/specimen";
import { Button } from "@/components/ui/button";
import type { Label } from "@/lib/api";
import { LABELS } from "@/lib/vocab";

// Real numbers only: the checked catalogue, the example reports, and the Questions page.
const PROOF = [
  { n: "7", label: "popular cards on Ritam's checked list" },
  { n: "140", label: "statements in the sample reports, each matched to the bank's exact line" },
  { n: "16", label: "common questions answered from RBI's own rules" },
];

const STEPS = [
  {
    title: "We find the official papers",
    body: "The bank's card page, its full list of charges (called the MITC), change notices and comparison sites. You don't have to search for anything.",
  },
  {
    title: "Nothing without proof",
    body: "The AI may only copy exact lines from the bank's papers. If Ritam can't find the line in the document, that point is thrown out.",
  },
  {
    title: "Fixed rules, not guesses",
    body: "Wrong figures, old information, missing charges and changes made without enough notice are flagged by fixed rules anyone can check.",
  },
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
              Ritam checks.
            </h1>
            <p className="mt-7 max-w-md text-lg leading-relaxed text-ink/80">
              Not sure your credit card&apos;s charges and benefits are what you were told? Type the card&apos;s name.
              Ritam reads the bank&apos;s official papers and tells you, in simple words, what&apos;s right, what changed and
              what to ask the bank, with proof.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Button asChild size="lg" className="h-12 rounded-md px-7 text-base font-semibold">
                <a href="#start">Get my card report</a>
              </Button>
              <Button asChild size="lg" variant="outline" className="h-12 rounded-md border-ink/45 bg-transparent px-7 text-base">
                <a href="#examples">See a sample report</a>
              </Button>
            </div>
            <p className="mt-4 text-sm text-mute">Free. No sign-up. Takes about 2 minutes.</p>
          </div>
          <HeroCards />
        </div>
      </section>

      <section aria-label="Ritam in numbers" className="border-b border-rule">
        <dl className="mx-auto grid max-w-6xl gap-px bg-rule sm:grid-cols-3">
          {PROOF.map((p) => (
            <div key={p.n} className="bg-night px-4 py-8 sm:px-6">
              <dt className="sr-only">{p.label}</dt>
              <dd>
                <span className="font-display text-5xl font-extrabold tracking-tight text-ink">{p.n}</span>
                <span className="mt-2 block max-w-[16rem] text-[0.9375rem] text-mute">{p.label}</span>
              </dd>
            </div>
          ))}
        </dl>
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
              A real case from a sample report. The highlighted line is the bank&apos;s own words, copied from its document.
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
            Three quick steps. Free, no sign-up, about 2 minutes.
          </p>
          <AuditForm />
        </section>

        <section id="examples" className="scroll-mt-6 border-t border-rule py-16" aria-labelledby="examples-title">
          <h2 id="examples-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
            See a sample report
          </h2>
          <p className="mb-8 mt-3 max-w-prose text-lg text-mute">
            Real reports made from Axis, HDFC and ICICI documents. Open one to see what you&apos;ll get.
          </p>
          <ExampleAudits />
        </section>

        <section className="border-t border-rule py-16" aria-labelledby="how-title">
          <h2 id="how-title" className="font-display text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">
            Why you can trust the report
          </h2>
          <ol className="mt-10 grid gap-px overflow-hidden rounded-lg border border-rule bg-rule md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="bg-night p-6">
                <p className="font-display text-sm font-semibold text-neon">Step {i + 1}</p>
                <h3 className="mt-2 font-display text-2xl font-semibold leading-tight text-ink">{s.title}</h3>
                <p className="mt-3 text-[0.9375rem] leading-relaxed text-ink/75">{s.body}</p>
              </li>
            ))}
          </ol>

          <h3 className="mt-14 font-display text-2xl font-semibold text-ink">What the labels mean</h3>
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
