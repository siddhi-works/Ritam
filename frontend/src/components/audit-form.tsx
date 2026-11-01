"use client";

import { ArrowLeft, FileUp, Link2, MessageSquareText, Plus, Search, TextCursorInput, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreep, Working } from "@/components/working";
import { apiPost, problemMessage, uploadFile, type DiscoverOut } from "@/lib/api";
import { ADDABLE_KINDS, SOURCE_KINDS } from "@/lib/vocab";

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

const QUICK_QUESTIONS = [
  "Tell me everything important about this card",
  "Are the fees and charges correct?",
  "Did the benefits or charges change recently?",
  "What should I check before applying?",
];

const FINDING_LINES = [
  "Looking the card up in Ritam's checked list",
  "Finding the bank's official card page",
  "Looking for the card's terms and charges (MITC)",
  "Checking comparison sites for the same card",
  "Collecting everything in one place",
];

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

const isFilled = (r: Row) =>
  Boolean((r.mode === "link" && r.url.trim()) || (r.mode === "file" && r.file) || ((r.mode === "text" || r.mode === "chat") && r.text.trim()));

export function AuditForm() {
  const router = useRouter();
  const formId = useId();
  const [question, setQuestion] = useState("");
  const [product, setProduct] = useState("");
  const [claim, setClaim] = useState("");
  const [manual, setManual] = useState<DiscoverOut | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manualHeading = useRef<HTMLHeadingElement>(null);
  const percent = useCreep(busy !== null, 95, 12);

  useEffect(() => {
    if (manual) manualHeading.current?.focus();
  }, [manual]);

  // The form collapses into a progress box; keep it in view.
  useEffect(() => {
    if (busy) document.getElementById("start")?.scrollIntoView({ block: "start" });
  }, [busy]);

  const update = (id: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const askedQuestion = () => question.trim() || (claim.trim() ? "What does this mean for me, and is it correct?" : QUICK_QUESTIONS[0]);

  function claimSource(): unknown[] {
    if (!claim.trim()) return [];
    return [{ type: "text", kind: "user_chat", text: claim.trim(), title: "Message to check", said_at: new Date().toISOString().slice(0, 10) }];
  }

  async function start(sources: unknown[], productName: string | null) {
    setBusy("Preparing your report");
    const res = await apiPost<{ audit_id: string }>("/api/audits", { question: askedQuestion(), product: productName, sources });
    router.push(`/audit/${res.audit_id}`);
  }

  async function check(e: React.FormEvent) {
    e.preventDefault();
    if (product.trim().length < 3 && !claim.trim()) {
      setError("Type your card's name, for example HDFC Millennia, or paste a message about it in step 3.");
      return;
    }
    setError(null);
    setBusy("Finding the right documents");
    try {
      const found = await apiPost<DiscoverOut>("/api/discover", {
        question: askedQuestion(),
        product: product.trim() || null,
        context: claim.trim() || null,
      });
      const urls = found.candidates
        .slice(0, MAX_SOURCES - 1)
        .map((c) => ({ type: "url", url: c.url, kind: c.kind, title: c.title }));
      if (urls.length === 0) {
        setManual(found);
        setRows((rs) => (rs.length ? rs : [newRow("link")]));
        setBusy(null);
        return;
      }
      await start([...urls, ...claimSource()], found.matched_card ?? (product.trim() || null));
    } catch (err) {
      setError(problemMessage(err));
      setBusy(null);
    }
  }

  function addOwnDocuments() {
    setError(null);
    setManual({ candidates: [], matched_card: null, searched: false, search_available: true, errors: [] });
    setRows((rs) => (rs.length ? rs : [newRow("link")]));
  }

  async function startManual(e: React.FormEvent) {
    e.preventDefault();
    const filled = rows.filter(isFilled);
    let problem: string | null = null;
    if (filled.length === 0 && !claim.trim()) problem = "Add at least one link, file or piece of text.";
    else if (rows.some((r) => r.mode === "link" && r.url.trim() && !/^https?:\/\//i.test(r.url.trim())))
      problem = "Links must start with http:// or https://";
    setError(problem);
    if (problem) return;
    try {
      const sources: unknown[] = claimSource();
      for (const r of filled) {
        if (r.mode === "link") sources.push({ type: "url", url: r.url.trim(), kind: r.kind });
        if (r.mode === "file" && r.file) {
          setBusy(`Uploading ${r.file.name}`);
          const s = await uploadFile(r.file, r.kind);
          sources.push({ type: "source", id: s.id });
        }
        if (r.mode === "text") sources.push({ type: "text", kind: "user_upload", text: r.text });
        if (r.mode === "chat")
          sources.push({ type: "text", kind: "user_chat", text: r.text, title: "What you were told", said_at: r.saidAt || null });
      }
      await start(sources.slice(0, MAX_SOURCES), manual?.matched_card ?? (product.trim() || null));
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

  if (busy)
    return (
      <Working
        title={busy}
        percent={percent}
        lines={busy.startsWith("Finding") ? FINDING_LINES : ["Getting your report ready", "Opening the progress page"]}
      />
    );

  if (!manual) {
    return (
      <form onSubmit={check} noValidate aria-describedby={`${formId}-error`} className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor={`${formId}-p`} className="text-[1.0625rem]">
            1. Type your credit card&apos;s name
          </Label>
          <Input
            id={`${formId}-p`}
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="For example: HDFC Millennia, SBI SimplyCLICK"
            autoComplete="off"
            className="h-12 bg-surface text-base"
          />
        </div>

        <fieldset className="space-y-3">
          <legend className="mb-1 text-[1.0625rem] font-medium">2. What do you want to know? Tap one, or type your own</legend>
          <div className="flex flex-wrap gap-2">
            {QUICK_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                aria-pressed={question === q}
                onClick={() => setQuestion(question === q ? "" : q)}
                className={`min-h-11 rounded-full border px-4 text-left text-[0.9375rem] ${
                  question === q ? "border-neon bg-neon text-night" : "border-rule bg-surface text-ink hover:border-ink"
                }`}
              >
                {q}
              </button>
            ))}
          </div>
          <Label htmlFor={`${formId}-q`} className="sr-only">
            Or type your own question
          </Label>
          <Textarea
            id={`${formId}-q`}
            value={QUICK_QUESTIONS.includes(question) ? "" : question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Type your own question, in any words"
            rows={2}
            className="bg-surface text-base"
          />
        </fieldset>

        <div className="space-y-2">
          <Label htmlFor={`${formId}-c`} className="text-[1.0625rem]">
            3. Want to verify a message or an ad? <span className="font-normal text-mute">(optional)</span>
          </Label>
          <Textarea
            id={`${formId}-c`}
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            placeholder="Paste an SMS or email from the bank, a line from an ad, or what customer care told you."
            rows={2}
            className="bg-surface text-base"
          />
          <p className="text-sm text-ink/70">Ritam tells you if it matches the bank&apos;s official papers.</p>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <Button type="submit" size="lg" className="h-12 px-7 text-base">
            <Search aria-hidden /> Get my free report
          </Button>
          <button
            type="button"
            onClick={addOwnDocuments}
            className="min-h-11 text-[0.9375rem] text-ink underline underline-offset-4 hover:no-underline"
          >
            I have the bank&apos;s PDF or link
          </button>
        </div>
        <p className="text-sm text-ink/70">Ritam finds the bank&apos;s official papers for you. You&apos;ll see your report in about 2 minutes.</p>
        {errorLine}
      </form>
    );
  }

  return (
    <form onSubmit={startManual} noValidate aria-describedby={`${formId}-error`} className="space-y-6">
      <div className="space-y-1">
        <h3 ref={manualHeading} tabIndex={-1} className="text-lg font-semibold outline-none">
          Add the documents to check
        </h3>
        <p className="text-[0.9375rem] text-ink/75">
          <ManualNote found={manual} product={product} />
        </p>
      </div>
      {rows.map((r, i) => (
        <SourceRow
          key={r.id}
          row={r}
          index={i}
          onChange={(p) => update(r.id, p)}
          onRemove={rows.length > 1 ? () => setRows((rs) => rs.filter((x) => x.id !== r.id)) : undefined}
        />
      ))}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={() => setRows((rs) => [...rs, newRow("link")])} disabled={rows.length >= MAX_SOURCES}>
          <Plus aria-hidden /> Add a link or file
        </Button>
        <Button type="button" variant="outline" onClick={() => setRows((rs) => [...rs, newRow("chat")])} disabled={rows.length >= MAX_SOURCES}>
          <MessageSquareText aria-hidden /> Paste what you were told
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" className="h-12 px-7 text-base">
          Get my free report
        </Button>
        <Button type="button" variant="ghost" onClick={() => setManual(null)}>
          <ArrowLeft aria-hidden /> Back
        </Button>
      </div>
      {errorLine}
    </form>
  );
}

function ManualNote({ found, product }: { found: DiscoverOut; product: string }) {
  if (found.errors.length) return <>Ritam&apos;s web search didn&apos;t answer just now. Add the bank&apos;s page or a PDF below.</>;
  if (!product.trim() && !found.matched_card && found.search_available && !found.searched && found.candidates.length === 0 && !found.errors.length)
    return <>Paste a link, upload a PDF from the bank, or paste text.</>;
  if (!found.matched_card && !product.trim())
    return <>Ritam couldn&apos;t tell which card this is about. Go back and type the card&apos;s name, or add a link below.</>;
  if (!found.search_available)
    return <>&ldquo;{product}&rdquo; isn&apos;t on Ritam&apos;s checked list yet. Add the bank&apos;s page or a PDF below.</>;
  return <>Ritam couldn&apos;t find documents for &ldquo;{product}&rdquo;. Check the spelling, or add the bank&apos;s page below.</>;
}

function SourceRow({
  row,
  index,
  onChange,
  onRemove,
}: {
  row: Row;
  index: number;
  onChange: (patch: Partial<Row>) => void;
  onRemove?: () => void;
}) {
  const id = useId();
  return (
    <div className="rounded-md border border-rule bg-surface p-3 sm:p-4">
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
                row.mode === m.value ? "border-neon bg-neon text-night" : "border-rule text-ink hover:border-ink"
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
                placeholder="https://www.bank.in/credit-cards/…"
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
                {ADDABLE_KINDS.map((k) => (
                  <SelectItem key={k} value={k}>
                    {SOURCE_KINDS[k]}
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
