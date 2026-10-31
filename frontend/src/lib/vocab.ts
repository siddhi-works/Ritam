import type { ChecklistOut, Label, Pack } from "./api";

/** Labels always render as icon + word, never colour alone (WCAG 1.4.1). */
export const LABELS: Record<Label, { name: string; meaning: string; text: string; bg: string; border: string }> = {
  sourced: {
    name: "Sourced",
    meaning: "Backed by an exact quote that Ritam matched in the document.",
    text: "text-sourced",
    bg: "bg-sourced-soft",
    border: "border-sourced",
  },
  ai_suggestion: {
    name: "AI suggestion",
    meaning: "Proposed by the AI, such as a question to check. Not a fact.",
    text: "text-ai",
    bg: "bg-ai-soft",
    border: "border-ai",
  },
  uncertain: {
    name: "Uncertain",
    meaning: "The evidence is mixed or unclear. Check before relying on it.",
    text: "text-uncertain",
    bg: "bg-uncertain-soft",
    border: "border-uncertain",
  },
};

/** What each finding type means, in plain words. */
export const MEANS: Record<string, string> = {
  conflict: "Two sources disagree. Only one can be right for you today.",
  stale: "This source seems out of date. Don't rely on its figure.",
  notice: "Banks must tell you before charges change. Check when you were told.",
  mitc_missing: "Something RBI expects in the card's key terms wasn't clearly found.",
  unanswered: "Part of your question isn't answered by the sources.",
  undated: "No date found, so you can't tell if this is current.",
  chat_mismatch: "What customer care said may not match the written terms.",
  single_origin: "Several sites agree, but they seem to copy one source.",
};

export const TYPE_NAMES: Record<string, string> = {
  conflict: "Conflict",
  stale: "Out of date",
  notice: "Notice period",
  mitc_missing: "Missing from terms",
  unanswered: "Unanswered",
  undated: "No date",
  chat_mismatch: "Told vs written",
  single_origin: "Copied source",
};

export const SOURCE_KINDS: Record<string, string> = {
  official_page: "Official web page",
  mitc_pdf: "Card terms (MITC)",
  kfs_pdf: "Key facts (KFS)",
  bank_notice: "Bank notice",
  rbi_rule: "RBI rule",
  aggregator: "Comparison site",
  news: "News article",
  forum: "Forum post",
  user_chat: "Customer-care chat",
  user_upload: "Your upload",
};

/** Kinds a person can choose when adding a link or file. */
export const ADDABLE_KINDS = ["official_page", "mitc_pdf", "bank_notice", "aggregator", "news", "rbi_rule"] as const;

/** Same source kinds, named for schemes and scholarships. */
export const GENERAL_KINDS = ["official_page", "bank_notice", "aggregator", "news"] as const;
export const GENERAL_KIND_NAMES: Record<string, string> = {
  official_page: "Official web page",
  bank_notice: "Official notice or circular",
  mitc_pdf: "Official guidelines",
  aggregator: "Third-party site",
};

/** Wording that differs between packs. */
export const PACK_WORDS: Record<Pack, { issuer: string; source: string; terms: string; thing: string; feature: string; ask: string }> = {
  credit_card: { issuer: "the bank", source: "Bank page", terms: "MITC", thing: "card", feature: "card feature", ask: "Ask the bank" },
  general: { issuer: "the official body", source: "Official page", terms: "notification", thing: "scheme", feature: "detail", ask: "Ask the office" },
};

export const ACTIONS: Record<ChecklistOut["action"], string> = {
  check_page: "Check",
  call_bank: "Ask the bank",
  grievance: "Write to the bank",
  ombudsman: "Escalate",
};

export const STEP_NAMES: Record<string, string> = {
  plan: "Understanding your question",
  fetch: "Fetching a source",
  extract: "Reading and quoting",
  analyse: "Comparing sources",
  summary: "Writing the summary",
};

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function sourceName(s: { title: string | null; url: string | null; publisher?: string | null }): string {
  return s.title || s.publisher || s.url || "Untitled source";
}
