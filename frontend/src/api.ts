export type Status = "verified" | "user_confirmed" | "conflict" | "unknown";

export interface Evidence {
  chunk_id?: string;
  text: string;
  source_file: string;
  source_category: string;
  locator: string;
  doc_title?: string;
  kind?: string;
  score?: number;
  citation: string;
}

export interface Answer {
  question_id: string;
  topic: string;
  question: string;
  status: Status;
  answer: string;
  rationale: string;
  confidence: number;
  evidence: Evidence[];
  followup: string;
  control_id: string;
  control_objective?: string;
  criticality: string;
  reviewer_playbook?: string;
  priority?: number;
  asked_count: number;
  updated_at: number;
}

export interface Stats {
  total_questions: number;
  by_status: Record<Status, number>;
  completion_pct: number;
  open_conflicts: number;
  facts_learned: number;
  avg_confidence: number;
}

export interface Conflict {
  id: string;
  question_id: string;
  topic: string;
  summary: string;
  side_a: string;
  side_b: string;
  severity: string;
  status: string;
  resolution: string;
  detected_by: string;
  at: number;
  question_hint?: string;
}

export interface Fact {
  id: string;
  subject: string;
  statement: string;
  actor: string;
  source: string;
  at: number;
}

export interface Health {
  ok: boolean;
  llm_provider: string;
  llm_model: string;
  reasoning_enabled: boolean;
  corpus: { chunks: number; files: number; error: string | null };
  prism: { configured: boolean; sent: number; failed: number; skipped: number };
  voice: { configured: boolean };
  profile: Stats;
}

export interface ChatResult {
  reply: string;
  evidence: Evidence[];
  recorded: {
    facts: Fact[];
    answers: { question_id: string; status: Status; answer: string; was_correction: boolean }[];
    corrections: unknown[];
    conflicts_resolved: Conflict[];
  };
  needs_followup?: boolean;
  followup_question?: string;
  priorities: Answer[];
  stats: Stats;
  degraded: boolean;
}

export interface InvestigateResult {
  question_id: string;
  question: string;
  status: Status;
  answer: string;
  rationale: string;
  confidence: number;
  evidence: Evidence[];
  followup: string;
  from_memory?: boolean;
  guard_notes?: string[];
  candidates_considered?: number;
  conflict?: Conflict | null;
}

async function req<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined && method === "POST" ? "POST" : method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/health", undefined, "GET"),
  bootstrap: () => req<{ questions: number; seeded: number }>("/bootstrap"),
  questionnaire: () =>
    req<{ stats: Stats; answers: Answer[]; topics: string[] }>("/questionnaire", undefined, "GET"),
  profile: () =>
    req<{ stats: Stats; facts: Fact[]; conflicts: Conflict[]; priorities: Answer[] }>(
      "/profile",
      undefined,
      "GET",
    ),
  chat: (message: string, opts?: { channel?: string; speaker?: string; session_id?: string }) =>
    req<ChatResult>("/chat", {
      message,
      channel: opts?.channel ?? "text",
      speaker: opts?.speaker ?? "employee",
      session_id: opts?.session_id ?? "analyst-session-1",
    }),
  investigate: (question_id: string, force = false) =>
    req<InvestigateResult>("/investigate", { question_id, force }),
  sweep: (limit = 66) => req<{ investigated: number; stats: Stats }>("/sweep", { limit }),
  detectConflicts: () =>
    req<{ probes_run: number; conflicts: Conflict[] }>("/conflicts/detect", {
      session_id: "analyst-session-1",
    }),
  resolveConflict: (conflict_id: string, resolution: string) =>
    req<Conflict>("/conflicts/resolve", { conflict_id, resolution, actor: "employee" }),
  search: (query: string) => req<{ hits: Evidence[] }>("/search", { query, k: 8 }),
  transcript: () =>
    req<{ messages: { role: string; content: string; channel: string; at: number }[] }>(
      "/transcript",
      undefined,
      "GET",
    ),
  voiceConfig: () =>
    req<{ enabled: boolean; agent_id: string; has_api_key: boolean }>(
      "/voice/config",
      undefined,
      "GET",
    ),
  voiceToken: () => req<{ token?: string }>("/voice/signed-url", undefined, "GET"),
  exportWorkbook: () => req<{ file: string; download: string }>("/export/workbook"),
  exportReport: () => req<{ file: string; download: string }>("/export/report"),
  prismHealth: () =>
    req<{
      configured: boolean;
      counters: Record<string, number>;
      recent: { step: string; ok: boolean; status: unknown; detail: string | null }[];
    }>("/prism/health", undefined, "GET"),
};
