export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Label = "sourced" | "ai_suggestion" | "uncertain";
export type AuditStatus = "queued" | "running" | "complete" | "partial" | "failed";

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: unknown;
  request_id?: string;
}

export class ApiError extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.title);
  }
}

export interface SourceOut {
  id: string;
  kind: string;
  status: string;
  title: string | null;
  url: string | null;
  publisher: string | null;
  authority_tier: number;
  doc_type: string | null;
  page_count: number | null;
  content_hash: string | null;
  fetch_method: string | null;
  fetched_at: string | null;
  archived_at: string | null;
  published_at: string | null;
  effective_from: string | null;
  announced_at: string | null;
  said_at: string | null;
  date_method: string | null;
  date_confidence: number | null;
  undated: boolean;
  error: string | null;
  meta: Record<string, unknown>;
}

export interface Evidence {
  claim_id: string;
  source_id: string;
  source: string;
  kind: string;
  tier: number;
  value: string;
  quote: string;
  page_no: number | null;
  conditions: string | null;
  valid_from: string | null;
}

export interface FindingOut {
  id: string;
  key: string | null;
  type: string;
  subtype: string | null;
  label: Label;
  severity: number;
  confidence: number;
  title: string;
  rule_id: string;
  attribute: string | null;
  detail: Record<string, unknown>;
  claim_ids: string[];
  source_ids: string[];
}

export interface ChecklistOut {
  rank: number;
  text: string;
  why: string;
  action: "check_page" | "call_bank" | "grievance" | "ombudsman";
  verify_url: string | null;
  finding_ids: string[];
}

export interface Cell {
  claim_id: string;
  value: string;
  quote: string;
  page_no: number | null;
  conditions: string | null;
  valid_from: string | null;
}

export interface MatrixRow {
  attribute: string;
  label: string;
  mitc_required: boolean;
  cells: Record<string, Cell[]>;
}

export interface Coverage {
  total: number;
  official: number;
  third_party: number;
  conflict: number;
  missing: number;
  by_attribute: Record<string, string>;
}

export interface TraceStep {
  step: string;
  ms?: number;
  [key: string]: unknown;
}

export interface AuditOut {
  id: string;
  question: string;
  product_name: string | null;
  status: AuditStatus;
  created_at: string;
  finished_at: string | null;
  plan: { attributes?: string[]; sub_questions?: { text: string; attributes: string[] }[]; planner?: string } | null;
  summary: { text: string; generated_by: string; label: Label } | null;
  stats: { trace?: TraceStep[]; findings?: number; claims_verified?: number; sources_total?: number; sources_failed?: number; error?: string; [k: string]: unknown };
  sources: SourceOut[];
  matrix: MatrixRow[];
  coverage: Coverage;
  findings: FindingOut[];
  checklist: ChecklistOut[];
}

/** A source found by discovery, confirmed by the user before the audit. */
export interface Candidate {
  url: string;
  title: string;
  kind: string;
  official: boolean;
  origin: "catalogue" | "search";
  why: string;
}

export interface DiscoverOut {
  candidates: Candidate[];
  not_indian?: boolean;
  message?: string | null;
  matched_card: string | null;
  searched: boolean;
  search_available: boolean;
  errors: string[];
}

export interface AuditListItem {
  id: string;
  question: string;
  status: AuditStatus;
  is_demo: boolean;
  created_at: string;
  findings: number | null;
}

export interface SourceView {
  source: SourceOut;
  pages: { page_no: number; text: string }[];
  highlights: { claim_id: string; page_no: number; char_start: number; char_end: number }[];
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const problem = (await res.json().catch(() => null)) as Problem | null;
    throw new ApiError(problem ?? { type: "about:blank", title: res.statusText || "Request failed", status: res.status });
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return handle<T>(await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers: { accept: "application/json" } }));
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function uploadFile(file: File, kind: string): Promise<SourceOut> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return handle<SourceOut>(await fetch(`${API_URL}/api/uploads`, { method: "POST", body: form }));
}

export function problemMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.problem.detail;
    return typeof d === "string" ? d : err.problem.title;
  }
  return "Ritam's server didn't answer. It may be waking up; try again in a minute.";
}

export interface StatementCharge {
  description: string;
  amount: number;
  kind: string;
}

export interface StatementFinding {
  title: string;
  detail: string;
  label: "sourced" | "uncertain";
  severity: number;
  charge: string | null;
  rule: string;
  ask: boolean;
  ref: string | null;
  amount: number | null;
}

export interface StatementOut {
  charges: StatementCharge[];
  dropped: number;
  findings: StatementFinding[];
  dates: { statement_date: string | null; payment_due_date: string | null; payment_received_date: string | null };
  total_due: string | null;
  minimum_due: string | null;
  card: string | null;
  report_id: string | null;
  masked: number;
  truncated: boolean;
  previous?: { statement_date: string | null; payment_due_date: string | null; total_due: string | null };
}

export async function checkStatement(file: File, card: string, lifetimeFree: boolean): Promise<StatementOut> {
  const form = new FormData();
  form.append("file", file);
  if (card.trim()) form.append("card", card.trim());
  form.append("lifetime_free", String(lifetimeFree));
  return handle<StatementOut>(await fetch(`${API_URL}/api/statements`, { method: "POST", body: form }));
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  return handle<T>(await fetch(`${API_URL}${path}`, { method: "POST", body: form }));
}

export async function compareStatements(
  previous: File,
  current: File,
  card: string,
  lifetimeFree: boolean,
): Promise<StatementOut> {
  const form = new FormData();
  form.append("previous", previous);
  form.append("current", current);
  if (card.trim()) form.append("card", card.trim());
  form.append("lifetime_free", String(lifetimeFree));
  return postForm<StatementOut>("/api/statements/compare", form);
}

export type Tool =
  | "fraud_help"
  | "statement_check"
  | "compare_bills"
  | "closure_claim"
  | "terms_history"
  | "complaint_dates"
  | "complaint_letter"
  | "card_report"
  | "guide";

export interface TriageOut {
  problem: string | null;
  title: string | null;
  tool: Tool;
  needs: string[];
  steps: string[];
  ref: string | null;
  letter_rule: string | null;
  matched_by: "rules" | "ai" | "none";
  also: string[];
  prefill: { card: string | null; card_id: string | null; dates: string[] };
  not_indian: boolean;
}

export interface TimelineStep {
  date: string;
  what: string;
  why: string;
}

export interface LetterFinding {
  rule: string;
  charge?: string | null;
  amount?: number | null;
  ref?: string | null;
}

export interface LetterOut {
  letter: string;
  bank: string | null;
  where_to_send: { text: string; quote: string; url: string | null; source: string | null } | null;
  timeline: TimelineStep[];
}

export interface ClosureOut {
  requested_on: string;
  due_by: string;
  closed_on: string | null;
  days_late: number;
  penalty: number;
  letter: string | null;
  note: string;
}

export interface TermValue {
  value: string;
  dated: string | null;
  dated_by: "effective" | "document" | "read";
  quote: string;
  source_url: string | null;
  source_title: string | null;
}

export interface TermSnapshot {
  dated: string;
  dated_by: string;
  values: TermValue[];
}

export interface TermsOut {
  card: string;
  since: string;
  today: string;
  terms: { attribute: string; label: string; then: TermSnapshot | null; now: TermSnapshot | null; changed: boolean | "maybe" }[];
  changes: { attribute: string; certain: boolean; before: TermSnapshot; after: TermSnapshot; from: string }[];
  coverage: { values: number; earliest: string | null; latest: string | null; note: string };
}

export function remindersUrl(complainedOn: string, title: string, repliedOn?: string): string {
  const q = new URLSearchParams({ complained_on: complainedOn, title });
  if (repliedOn) q.set("replied_on", repliedOn);
  return `${API_URL}/api/cases/reminders.ics?${q}`;
}
