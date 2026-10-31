import { AuditForm } from "@/components/audit-form";
import { ExampleAudits } from "@/components/example-audits";
import { LabelTag } from "@/components/label-tag";
import { Specimen } from "@/components/specimen";
import { Button } from "@/components/ui/button";
import type { Label } from "@/lib/api";
import { LABELS } from "@/lib/vocab";

const STEPS = [
  {
    title: "It finds and reads the sources",
    body: "Ritam gathers the bank's pages, card terms (MITC), notices and comparison sites for you, and marks which are official. You can add a chat or letter too.",
  },
  {
    title: "The AI may only quote",
    body: "Each claim must come with an exact quote. Ritam finds that quote in the document and drops any claim it can't find, or whose numbers don't match.",
  },
  {
    title: "Fixed rules decide",
    body: "Conflicts, outdated figures, missing terms and notice periods are found by rules anyone can inspect, not by the AI's opinion.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-6xl px-4 sm:px-6">
      <section className="grid items-start gap-10 py-12 md:grid-cols-[1fr_1.05fr] md:py-20" aria-labelledby="hero-title">
        <div className="max-w-xl">
          <h1 id="hero-title" className="text-[2.75rem] font-semibold leading-[1.05] tracking-[-0.02em] text-ink sm:text-[3.75rem]">
            Banks talk.
            <br />
            Ritam checks.
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-ink/80">
            Name a credit card and ask your question. Ritam finds the bank&apos;s pages, terms and comparison sites,
            then shows what&apos;s missing, what disagrees and what&apos;s out of date, with the exact line from the
            document behind every point. It works for scholarships and government schemes too.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg" className="h-11 px-6 text-base">
              <a href="#start">Start an audit</a>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-11 bg-white px-6 text-base">
              <a href="#examples">See finished audits</a>
            </Button>
          </div>
        </div>
        <Specimen />
      </section>

      <section id="start" className="scroll-mt-6 border-t border-rule py-12" aria-labelledby="start-title">
        <h2 id="start-title" className="text-2xl font-semibold tracking-tight text-ink">
          Start an audit
        </h2>
        <p className="mb-8 mt-2 max-w-prose text-mute">
          Name what you want checked and ask one question. Ritam finds the sources; you confirm them before it starts.
        </p>
        <AuditForm />
      </section>

      <section id="examples" className="scroll-mt-6 border-t border-rule py-12" aria-labelledby="examples-title">
        <h2 id="examples-title" className="text-2xl font-semibold tracking-tight text-ink">
          Finished audits on real documents
        </h2>
        <p className="mb-6 mt-2 max-w-prose text-mute">
          Built from public Axis, HDFC and ICICI documents, and a government scholarship notice. They open instantly.
        </p>
        <ExampleAudits />
      </section>

      <section className="border-t border-rule py-12" aria-labelledby="how-title">
        <h2 id="how-title" className="text-2xl font-semibold tracking-tight text-ink">
          How Ritam decides
        </h2>
        <ol className="mt-8 grid gap-8 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="border-l-2 border-ink pl-4">
              <p className="text-sm text-mute">Step {i + 1}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{s.title}</h3>
              <p className="mt-2 text-[0.9375rem] leading-relaxed text-ink/80">{s.body}</p>
            </li>
          ))}
        </ol>

        <h3 className="mt-12 text-lg font-semibold text-ink">What the labels mean</h3>
        <dl className="mt-4 grid gap-4 md:grid-cols-3">
          {(Object.keys(LABELS) as Label[]).map((k) => (
            <div key={k}>
              <dt>
                <LabelTag label={k} />
              </dt>
              <dd className="mt-2 text-[0.9375rem] text-ink/80">{LABELS[k].meaning}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}
