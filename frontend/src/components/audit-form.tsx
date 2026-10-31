"use client";

import {
  ArrowLeft,
  CreditCard,
  ExternalLink,
  FileUp,
  Globe,
  GraduationCap,
  Link2,
  MessageSquareText,
  Plus,
  Search,
  ShieldCheck,
  TextCursorInput,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiPost, problemMessage, uploadFile, type Candidate, type DiscoverOut, type Pack } from "@/lib/api";
import { ADDABLE_KINDS, GENERAL_KIND_NAMES, GENERAL_KINDS, SOURCE_KINDS } from "@/lib/vocab";

type Mode = "link" | "file" | "text" | "chat";
interface Row {
  id: number;
  mode: Mode;
  url: string;
  kind: string;
  file: File | null;
  text: string;
  saidAt: string;
}

const MODES: { value: Mode; label: string; icon: typeof Link2 }[] = [
  { value: "link", label: "Link", icon: Link2 },
  { value: "file", label: "PDF or saved page", icon: FileUp },
  { value: "text", label: "Pasted text", icon: TextCursorInput },
  { value: "chat", label: "What you were told", icon: MessageSquareText },
];

const PACKS: Record<
  Pack,
  { label: string; icon: typeof CreditCard; name: string; namePlaceholder: string; question: string; hint: string; own: string }
> = {
  credit_card: {
    label: "A credit card",
    icon: CreditCard,
    name: "Which card?",
    namePlaceholder: "e.g. HDFC Millennia",
    question: "Did this card's fees or benefits change, and was I told in time?",
    hint: "Popular cards are on Ritam's checked list. Others are looked up on the web.",
    own: "What customer care told you, or a letter or email from the bank, lets Ritam check it against the written terms.",
  },
  general: {
    label: "A scholarship or scheme",
    icon: GraduationCap,
    name: "Which scholarship or scheme?",
    namePlaceholder: "e.g. Post-matric scholarship for SC students",
    question: "What is the last date to apply, and who is eligible?",
    hint: "Ritam searches the web and lists official government sites first.",
    own: "A circular from your college, or what a helpline told you, lets Ritam check it against the official notice.",
  },
};

const MAX_SOURCES = 12;

let nextId = 1;
const newRow = (mode: Mode = "link"): Row => ({
  id: nextId++,
  mode,
  url: "",
  kind: "official_page",
  file: null,
  text: "",
  saidAt: "",
});

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

const isFilled = (r: Row) =>
  Boolean((r.mode === "link" && r.url.trim()) || (r.mode === "file" && r.file) || ((r.mode === "text" || r.mode === "chat") && r.text.trim()));

export function AuditForm() {
  const router = useRouter();
  const formId = useId();
  const [pack, setPack] = useState<Pack>("credit_card");
  const [question, setQuestion] = useState("");
  const [product, setProduct] = useState("");
  const [found, setFound] = useState<DiscoverOut | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const reviewing = found !== null;
  const meta = PACKS[pack];

  useEffect(() => {
    if (reviewing) reviewHeading.current?.focus();
  }, [reviewing]);

  const update = (id: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const total = picked.size + rows.filter(isFilled).length;

  function choosePack(p: Pack) {
    if (p !== pack) setProduct("");
    setPack(p);
    setFound(null);
    setError(null);
  }

  function checkQuestion(): string | null {
    if (question.trim().length < 5) return "Write your question in a few words first.";
    return null;
  }

  async function findSources(e: React.FormEvent) {
    e.preventDefault();
    const problem =
      checkQuestion() ??
      (product.trim().length < 3 ? `Tell Ritam ${pack === "credit_card" ? "which card" : "which scholarship or scheme"} to check.` : null);
    setError(problem);
    if (problem) return;
    setBusy("Finding sources…");
    try {
      const res = await apiPost<DiscoverOut>("/api/discover", { question: question.trim(), product: product.trim(), pack });
      setFound(res);
      setPicked(new Set(res.candidates.slice(0, MAX_SOURCES).map((c) => c.url)));
      if (res.candidates.length === 0 && rows.length === 0) setRows([newRow("link")]);
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function addOwnDocuments() {
    const problem = checkQuestion();
    setError(problem);
    if (problem) return;
    setFound({ candidates: [], matched_card: null, searched: false, search_available: true, errors: [] });
    setPicked(new Set());
    if (rows.length === 0) setRows([newRow("link")]);
  }

  async function startAudit(e: React.FormEvent) {
    e.preventDefault();
    let problem: string | null = null;
    if (total === 0) problem = "Tick at least one source, or add your own.";
    else if (total > MAX_SOURCES) problem = `Choose at most ${MAX_SOURCES} sources; untick some first.`;
    else if (rows.some((r) => r.mode === "link" && r.url.trim() && !/^https?:\/\//i.test(r.url.trim())))
      problem = "Links must start with http:// or https://";
    setError(problem);
    if (problem) return;
    try {
      const sources: unknown[] = (found?.candidates ?? [])
        .filter((c) => picked.has(c.url))
        .map((c) => ({ type: "url", url: c.url, kind: c.kind, title: c.title }));
      for (const r of rows) {
        if (r.mode === "link" && r.url.trim()) sources.push({ type: "url", url: r.url.trim(), kind: r.kind });
        if (r.mode === "file" && r.file) {
          setBusy(`Uploading ${r.file.name}…`);
          const s = await uploadFile(r.file, r.kind);
          sources.push({ type: "source", id: s.id });
        }
        if (r.mode === "text" && r.text.trim()) sources.push({ type: "text", kind: "user_upload", text: r.text });
        if (r.mode === "chat" && r.text.trim())
          sources.push({ type: "text", kind: "user_chat", text: r.text, title: "What you were told", said_at: r.saidAt || null });
      }
      setBusy("Starting the audit…");
      const res = await apiPost<{ audit_id: string }>("/api/audits", {
        question: question.trim(),
        product: found?.matched_card ?? (product.trim() || null),
        pack,
        sources,
      });
      router.push(`/audit/${res.audit_id}`);
    } catch (err) {
      setError(problemMessage(err));
      setBusy(null);
    }
  }

  const errorLine = (
    <p id={`${formId}-error`} role="alert" className="min-h-6 text-[0.9375rem] font-medium text-destructive">
      {error}
    </p>
  );

  if (!found) {
    return (
      <form onSubmit={findSources} noValidate aria-describedby={`${formId}-error`} className="space-y-6">
        <div role="radiogroup" aria-label="What are you checking?" className="flex flex-wrap gap-2">
          {(Object.keys(PACKS) as Pack[]).map((p) => {
            const Icon = PACKS[p].icon;
            return (
              <button
                key={p}
                type="button"
                role="radio"
                aria-checked={pack === p}
                onClick={() => choosePack(p)}
                className={`inline-flex min-h-11 items-center gap-2 rounded-full border px-4 text-[0.9375rem] ${
                  pack === p ? "border-ink bg-ink text-white" : "border-rule bg-white text-ink hover:border-ink"
                }`}
              >
                <Icon aria-hidden className="size-4" />
                {PACKS[p].label}
              </button>
            );
          })}
        </div>

        <div className="grid gap-5 md:grid-cols-[1fr_1.4fr]">
          <div className="space-y-2">
            <Label htmlFor={`${formId}-p`} className="text-[0.9375rem]">
              {meta.name}
            </Label>
            <Input
              id={`${formId}-p`}
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder={meta.namePlaceholder}
              autoComplete="off"
              className="bg-white text-base"
            />
            <p className="text-sm text-mute">{meta.hint}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${formId}-q`} className="text-[0.9375rem]">
              What do you want to know?
            </Label>
            <Textarea
              id={`${formId}-q`}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={meta.question}
              rows={3}
              className="bg-white text-base"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <Button type="submit" size="lg" disabled={!!busy} className="h-11 px-6 text-base">
            <Search aria-hidden /> {busy ?? "Find sources"}
          </Button>
          <button
            type="button"
            onClick={addOwnDocuments}
            className="min-h-11 text-[0.9375rem] text-ink underline underline-offset-4 hover:no-underline"
          >
            I have my own documents
          </button>
        </div>
        {errorLine}
      </form>
    );
  }

  const cands = found.candidates;
  return (
    <form onSubmit={startAudit} noValidate aria-describedby={`${formId}-error`} className="space-y-6">
      <div className="space-y-1">
        <h3 ref={reviewHeading} tabIndex={-1} className="text-lg font-semibold outline-none">
          {cands.length ? `Ritam found ${cands.length} source${cands.length === 1 ? "" : "s"}` : "Add the sources to check"}
        </h3>
        <p className="text-[0.9375rem] text-mute">
          <FoundNote found={found} product={product} pack={pack} />
        </p>
      </div>

      {cands.length > 0 && (
        <fieldset>
          <legend className="sr-only">Sources to include in the audit</legend>
          <ul className="divide-y divide-rule rounded-md border border-rule bg-white">
            {cands.map((c) => (
              <CandidateRow
                key={c.url}
                c={c}
                pack={pack}
                checked={picked.has(c.url)}
                onToggle={(on) =>
                  setPicked((s) => {
                    const n = new Set(s);
                    if (on) n.add(c.url);
                    else n.delete(c.url);
                    return n;
                  })
                }
              />
            ))}
          </ul>
        </fieldset>
      )}

      <section aria-labelledby={`${formId}-own`} className="space-y-3">
        <h4 id={`${formId}-own`} className="text-[0.9375rem] font-medium">
          Add your own source <span className="font-normal text-mute">(optional)</span>
        </h4>
        <p className="text-sm text-mute">{meta.own}</p>
        {rows.map((r, i) => (
          <SourceRow
            key={r.id}
            row={r}
            index={i}
            pack={pack}
            onChange={(p) => update(r.id, p)}
            onRemove={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
          />
        ))}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => setRows((rs) => [...rs, newRow("link")])} disabled={total >= MAX_SOURCES}>
            <Plus aria-hidden /> Add a link or file
          </Button>
          <Button type="button" variant="outline" onClick={() => setRows((rs) => [...rs, newRow("chat")])} disabled={total >= MAX_SOURCES}>
            <MessageSquareText aria-hidden /> Paste what you were told
          </Button>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!!busy || total === 0} className="h-11 px-6 text-base">
          {busy ? "Working…" : `Start audit with ${total} source${total === 1 ? "" : "s"}`}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setFound(null)} disabled={!!busy}>
          <ArrowLeft aria-hidden /> Change question
        </Button>
        <p className="text-sm text-mute" aria-live="polite">
          {busy ?? "Takes about 2 minutes. You'll see each step as it happens."}
        </p>
      </div>
      {errorLine}
    </form>
  );
}

function FoundNote({ found, product, pack }: { found: DiscoverOut; product: string; pack: Pack }) {
  if (found.candidates.length === 0) {
    if (found.errors.length) return <>The web search didn&apos;t answer just now. Add a link or document below, or try again later.</>;
    if (!found.search_available)
      return pack === "credit_card" ? (
        <>
          &ldquo;{product}&rdquo; isn&apos;t on Ritam&apos;s checked list yet, and web search is off on this server. Add a link or
          document below.
        </>
      ) : (
        <>Web search is off on this server, so add the official page or notice below.</>
      );
    if (found.searched) return <>The web search found nothing usable. Add a link or document below.</>;
    return <>Paste a link, upload a PDF, or paste text below.</>;
  }
  return (
    <>
      {found.matched_card ? (
        <>
          From Ritam&apos;s checked list for <strong className="font-medium text-ink">{found.matched_card}</strong>
          {found.searched ? ", plus a web search" : ""}.
        </>
      ) : (
        <>From a web search.</>
      )}{" "}
      Official sources come first. Untick anything you don&apos;t want checked.
    </>
  );
}

function CandidateRow({ c, pack, checked, onToggle }: { c: Candidate; pack: Pack; checked: boolean; onToggle: (on: boolean) => void }) {
  const id = useId();
  return (
    <li className="flex items-start gap-3 p-3 sm:p-4">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="mt-0.5 size-5 shrink-0 accent-ink"
      />
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className="block cursor-pointer font-medium leading-snug break-words">
          {c.title}
        </label>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          {c.official ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-sourced bg-sourced-soft px-2 py-0.5 font-medium text-sourced">
              <ShieldCheck aria-hidden className="size-3.5" /> Official
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-rule px-2 py-0.5 text-mute">
              <Globe aria-hidden className="size-3.5" /> Third-party
            </span>
          )}
          <span className="text-mute">{(pack === "general" && GENERAL_KIND_NAMES[c.kind]) || SOURCE_KINDS[c.kind] || c.kind}</span>
          <span className="break-all text-mute">{hostOf(c.url)}</span>
        </div>
      </div>
      <a
        href={c.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-md text-mute hover:bg-paper hover:text-ink"
        aria-label={`Open ${c.title} in a new tab`}
      >
        <ExternalLink aria-hidden className="size-4" />
      </a>
    </li>
  );
}

function SourceRow({
  row,
  index,
  pack,
  onChange,
  onRemove,
}: {
  row: Row;
  index: number;
  pack: Pack;
  onChange: (patch: Partial<Row>) => void;
  onRemove?: () => void;
}) {
  const id = useId();
  const kinds = pack === "credit_card" ? ADDABLE_KINDS : GENERAL_KINDS;
  return (
    <div className="rounded-md border border-rule bg-white p-3 sm:p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div role="radiogroup" aria-label={`Source ${index + 1} type`} className="flex flex-wrap gap-1.5">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              role="radio"
              aria-checked={row.mode === m.value}
              onClick={() => onChange({ mode: m.value })}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-sm ${
                row.mode === m.value ? "border-ink bg-ink text-white" : "border-rule text-ink hover:border-ink"
              }`}
            >
              <m.icon aria-hidden className="size-4" />
              {m.label}
            </button>
          ))}
        </div>
        {onRemove && (
          <Button type="button" variant="ghost" size="icon" onClick={onRemove} aria-label={`Remove source ${index + 1}`}>
            <X aria-hidden />
          </Button>
        )}
      </div>

      {(row.mode === "link" || row.mode === "file") && (
        <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
          {row.mode === "link" ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-url`} className="sr-only">
                Link
              </Label>
              <Input
                id={`${id}-url`}
                type="url"
                inputMode="url"
                value={row.url}
                onChange={(e) => onChange({ url: e.target.value })}
                placeholder={pack === "credit_card" ? "https://www.bank.in/credit-cards/…" : "https://scholarships.gov.in/…"}
                className="text-base"
              />
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-file`} className="sr-only">
                File
              </Label>
              <Input
                id={`${id}-file`}
                type="file"
                accept=".pdf,.html,.htm,.txt,application/pdf,text/html,text/plain"
                onChange={(e) => onChange({ file: e.target.files?.[0] ?? null })}
                className="text-base"
              />
              <p className="text-xs text-mute">PDF, saved web page (Ctrl+S) or text. Up to 20 MB.</p>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-kind`} className="sr-only">
              What is it?
            </Label>
            <Select value={row.kind} onValueChange={(v) => onChange({ kind: v })}>
              <SelectTrigger id={`${id}-kind`} className="w-full text-base">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {kinds.map((k) => (
                  <SelectItem key={k} value={k}>
                    {pack === "credit_card" ? SOURCE_KINDS[k] : (GENERAL_KIND_NAMES[k] ?? SOURCE_KINDS[k])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      {(row.mode === "text" || row.mode === "chat") && (
        <div className="space-y-3">
          <Label htmlFor={`${id}-text`} className="sr-only">
            {row.mode === "chat" ? "Chat transcript" : "Text"}
          </Label>
          <Textarea
            id={`${id}-text`}
            value={row.text}
            onChange={(e) => onChange({ text: e.target.value })}
            rows={4}
            placeholder={
              row.mode === "chat"
                ? "Paste what customer care said. Card numbers, phones and emails are masked automatically."
                : "Paste terms, an email from the bank, or any text."
            }
            className="text-base"
          />
          {row.mode === "chat" && (
            <div className="flex flex-wrap items-center gap-3">
              <Label htmlFor={`${id}-date`} className="text-sm">
                When was this said?
              </Label>
              <Input
                id={`${id}-date`}
                type="date"
                value={row.saidAt}
                onChange={(e) => onChange({ saidAt: e.target.value })}
                className="w-auto text-base"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
