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
  pack: Pack;
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

export type Pack = "credit_card" | "general";

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
