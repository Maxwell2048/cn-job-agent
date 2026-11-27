// Typed client for the cn-job-agent API (src/cn_job_agent/api). Shapes mirror api/views.py.

export type Verdict = "direct" | "related" | "insufficient";
export type RunStatus = "running" | "interrupted" | "rejected" | "done" | "failed";
export type PostingStatus = "new" | "review" | "screened_out" | "matched" | "failed";
export type Severity = "hard" | "soft" | "info";

export interface Counts { direct: number; related: number; insufficient: number; error: number }

export interface RunBrief {
  id: string;
  status: RunStatus;
  decision: "pass" | "review" | "reject" | "error" | null;
  score: number | null;
  label: string | null;
  required_covered: number | null;
  required_total: number | null;
  counts: Counts | null;
  started_at: string | null;
  finished_at: string | null;
  posting_id?: number;
  posting_title?: string;
}

export interface PostingBrief {
  id: number;
  title: string;
  company: string;
  company_key: string | null;
  city: string;
  channel: string;
  source: string;
  url: string;
  status: PostingStatus;
  posted_at: string;
  created_at: string | null;
  latest_run: RunBrief | null;
}

export interface Flag { code: string; severity: Severity; message: string; quote: string }

export interface Evidence {
  candidate_id: string;
  quote: string;
  project: string;
  section: string;
  source: string;
  line_start: number;
  line_end: number;
}

export interface Match {
  requirement_id: string;
  text: string;
  category: string;
  importance: "required" | "preferred" | "unspecified";
  source_quote: string;
  verdict: Verdict | null;
  processing_status: string;
  reason: string;
  evidence: Evidence[];
  missing_aspects: string[];
  questions_for_user: string[];
  errors: string[];
}

export interface TraceStep { node: string; seconds?: number; requirement?: string }

export interface RunDetail extends RunBrief {
  posting_id: number;
  posting_title: string;
  screening: { decision?: string; flags?: Flag[] };
  summary: { score?: number | null; label?: string; formula?: string; requirements?: number;
             condition_insufficient_share?: number | null };
  trace: TraceStep[];
  versions: Record<string, unknown>;
  error: string;
  has_report: boolean;
  matches: Match[];
}

export interface Program {
  title: string;
  window_start: string | null;
  window_end: string | null;
  window_text: string;
  basis: string;
  status_text: string;
  deadline: string | null;
  deadline_text: string;
  roles: string[];
  cities: string[];
  requirements: string[];
  apply_limit: string;
  confidence: string;
  sources: { label: string; url: string }[];
  verdict: string | null;
  verdict_label: string | null;
  verdict_reason: string | null;
  city_match?: "city" | "province" | "nationwide" | null;
  matched_cities?: string[];
}

export interface PostingDetail extends PostingBrief {
  jd_text: string;
  company_detail: { key: string; name: string; portal: string; programs: Program[] } | null;
  runs: RunBrief[];
  latest: RunDetail | null;
}

export interface CompanyRow { key: string; name: string; sector: string; portal: string; note: string; programs: Program[] }

export interface CollectionBrief {
  id: string;
  mode: string;
  status: string;
  stats: { searches?: number; seen?: number; saved?: number; duplicates?: number; errors?: number };
  started_at: string | null;
  finished_at: string | null;
  error: string;
}

export interface CollectionDetail extends CollectionBrief {
  plan: { source: string; keyword: string; hits: number; in_target_city?: number; error?: string }[];
  trace: { type: string; tool?: string; args?: Record<string, unknown>; text?: string; keywords?: string[] }[];
  saved: { posting_id: number; id: string; title: string; reason: string; source: string }[];
}

export interface Overview {
  postings: Partial<Record<PostingStatus, number>>;
  runs: Partial<Record<RunStatus, number>>;
  companies: number;
  programs: number;
  profile: { roles: { key: string; label: string; keywords?: string[] }[]; cities: string[]; channels: string[] } | null;
  recent_runs: RunBrief[];
  recent_collections: CollectionBrief[];
}

export interface ModelInfo {
  ok: boolean;
  provider: string;
  label?: string;
  model?: string;
  host?: string;
  cloud?: boolean;
  privacy?: string;
  error?: string;
}

export interface Insights {
  by_category: Record<string, Partial<Record<Verdict | "error", number>>>;
  top_gaps: { text: string; count: number }[];
}

export interface GraphShape {
  nodes: { id: string }[];
  edges: { source: string; target: string; conditional: boolean }[];
}

/** One Server-Sent Event from a run or a collection. */
export interface LiveEvent {
  node: string;
  at?: string;
  seconds?: number;
  decision?: string;
  requirements?: number;
  requirement_id?: string;
  verdict?: Verdict | null;
  text?: string;
  score?: number | null;
  label?: string;
  question?: string;
  approved?: boolean | null;
  source?: string;
  keyword?: string;
  hits?: number;
  title?: string;
  posting_id?: number;
  mode?: string;
}

export interface Cited { text: string; cites: string[] }

export interface MaterialsData {
  run_id: string;
  created_at: string;
  version: string;
  model: string;
  prompt_version: string;
  posting: { id: number; title: string; company: string; city: string };
  draft: {
    target_title: string;
    summary: Cited;
    projects: { project_id: string; title: string; role: string; period: string;
                bullets: { label: string; text: string; cites: string[] }[] }[];
    greeting: Cited;
  };
  skills: [string, string][];
  warnings: string[];
  gaps: string[];
  citations: Record<string, { project: string; section: string; source: string; line_start: number; line_end: number }>;
  files: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  if (!response.ok) {
    let message = text;
    try {
      message = JSON.parse(text).detail ?? text;
    } catch {
      /* plain text error */
    }
    throw new ApiError(response.status, typeof message === "string" ? message : JSON.stringify(message));
  }
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? JSON.parse(text) : text) as T;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  overview: () => request<Overview>("/api/overview"),
  model: () => request<ModelInfo>("/api/model"),
  insights: () => request<Insights>("/api/insights"),
  graph: () => request<GraphShape>("/api/graph"),
  postings: (params: { status?: string; q?: string } = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<PostingBrief[]>(`/api/postings?${query}`);
  },
  posting: (id: number | string) => request<PostingDetail>(`/api/postings/${id}`),
  addPosting: (body: { text: string; title?: string; company?: string; city?: string; url?: string; channel?: string }) =>
    post<{ created: boolean; posting: PostingBrief }>("/api/postings", body),
  startRun: (postingId: number, options: { force?: boolean; auto_approve?: boolean } = {}) =>
    post<{ run_id: string }>(`/api/postings/${postingId}/runs`, options),
  runs: () => request<RunBrief[]>("/api/runs"),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  resume: (id: string, approve: boolean | null) => post<{ run_id: string }>(`/api/runs/${id}/resume`, { approve }),
  report: (id: string) => request<string>(`/api/runs/${id}/report`),
  materials: (runId: string) => request<MaterialsData>(`/api/runs/${runId}/materials`),
  generateMaterials: (runId: string) => post<{ job: string }>(`/api/runs/${runId}/materials`, {}),
  materialFile: (runId: string, name: string) => `/api/runs/${runId}/materials/${name}`,
  collections: () => request<CollectionBrief[]>("/api/collections"),
  collection: (id: string) => request<CollectionDetail>(`/api/collections/${id}`),
  startCollection: (mode: string) => post<{ collection_id: string }>("/api/collections", { mode }),
  companies: (cities: string[] = [], all = false) => {
    const query = new URLSearchParams();
    cities.forEach((c) => query.append("city", c));
    if (all) query.set("all", "true");
    return request<CompanyRow[]>(`/api/companies?${query}`);
  },
};
