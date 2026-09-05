import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConversationProvider } from "@elevenlabs/react";
import { api } from "./api";
import type { Answer, Conflict, Evidence, Fact, Health, Stats, Status } from "./api";
import {
  Chip,
  ConflictCard,
  Confidence,
  EvidenceCard,
  Legend,
  ProgressBar,
  QuestionCard,
  TopicBreakdown,
} from "./components";
import { VoicePanel, voiceClientTools } from "./Voice";

type Tab = "questionnaire" | "conflicts" | "evidence" | "memory" | "prism";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  channel: string;
  evidence?: Evidence[];
  recorded?: { question_id: string; answer: string; was_correction: boolean }[];
}

const SUGGESTIONS = [
  "Is MFA enabled?",
  "Where is customer data stored?",
  "Do you encrypt data at rest?",
  "How often are backups performed?",
  "Who has access to production?",
  "Do you have an employee offboarding process?",
];

function Inner() {
  const [health, setHealth] = useState<Health>();
  const [stats, setStats] = useState<Stats>();
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [priorities, setPriorities] = useState<Answer[]>([]);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [tab, setTab] = useState<Tab>("questionnaire");
  const [filter, setFilter] = useState<Status | "all">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string>();
  const [searchHits, setSearchHits] = useState<Evidence[]>([]);
  const [searchQ, setSearchQ] = useState("");
  const [traces, setTraces] = useState<
    { step: string; ok: boolean; status: unknown; detail: string | null }[]
  >([]);
  const chatEnd = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const [q, p, h] = await Promise.all([api.questionnaire(), api.profile(), api.health()]);
    setAnswers(q.answers);
    setStats(q.stats);
    setConflicts(p.conflicts);
    setFacts(p.facts);
    setPriorities(p.priorities);
    setHealth(h);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        await api.bootstrap();
        await refresh();
        const t = await api.transcript();
        setMessages(
          t.messages.map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            channel: m.channel,
          })),
        );
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [refresh]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (tab !== "prism") return;
    const load = () => api.prismHealth().then((p) => setTraces(p.recent)).catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [tab]);

  const send = useCallback(
    async (text: string, channel = "text") => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setMessages((m) => [...m, { role: "user", content: trimmed, channel }]);
      setInput("");
      setBusy("chat");
      try {
        const res = await api.chat(trimmed, { channel });
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            content: res.reply,
            channel,
            evidence: res.evidence.slice(0, 3),
            recorded: res.recorded.answers,
          },
        ]);
        setStats(res.stats);
        setPriorities(res.priorities);
        await refresh();
      } catch (err) {
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            content: `Could not reach the analyst: ${
              err instanceof Error ? err.message : String(err)
            }`,
            channel,
          },
        ]);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const investigate = useCallback(
    async (id: string, force: boolean) => {
      setBusy(`q-${id}`);
      try {
        await api.investigate(id, force);
        await refresh();
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const runAction = useCallback(
    async (key: string, fn: () => Promise<unknown>, done?: (r: unknown) => void) => {
      setBusy(key);
      setNotice(undefined);
      try {
        const r = await fn();
        done?.(r);
        await refresh();
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const visible = useMemo(
    () => (filter === "all" ? answers : answers.filter((a) => a.status === filter)),
    [answers, filter],
  );
  const openConflicts = conflicts.filter((c) => c.status === "open");

  const onVoiceTurn = useCallback((e: { role: "user" | "assistant"; content: string }) => {
    setMessages((m) => [...m, { ...e, channel: "voice" }]);
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <h1>RiskAndCompliance</h1>
          <span>AI Security Analyst</span>
        </div>
        {stats && <ProgressBar stats={stats} />}
        {stats && <Legend stats={stats} />}
        <div className="spacer" />
        <span className={`pill ${health?.reasoning_enabled ? "ok" : "warn"}`}>
          <i className="dot" />
          {health?.reasoning_enabled ? health.llm_model : "no LLM key"}
        </span>
        <span className={`pill ${health?.prism.configured ? "ok" : "warn"}`}>
          <i className="dot" />
          PRISM{" "}
          <strong>
            {health?.prism.configured ? `${health.prism.sent} traces` : "not configured"}
          </strong>
        </span>
        <span className="pill">
          <i className="dot" />
          corpus <strong>{health?.corpus.chunks ?? 0}</strong> chunks / {health?.corpus.files ?? 0}{" "}
          files
        </span>
      </header>

      {notice && (
        <div className="banner alert">
          {notice}
          <div className="spacer" />
          <button onClick={() => setNotice(undefined)}>Dismiss</button>
        </div>
      )}
      {openConflicts.length > 0 && tab !== "conflicts" && (
        <div className="banner alert">
          {openConflicts.length} contradiction{openConflicts.length > 1 ? "s" : ""} found between
          what the policies claim and what the assessments and infrastructure records show.
          <div className="spacer" />
          <button onClick={() => setTab("conflicts")}>Review</button>
        </div>
      )}
      {health && !health.reasoning_enabled && (
        <div className="banner info">
          No reasoning model configured. Evidence retrieval and conflict detection still work; every
          answer stays marked unknown rather than guessed. Add an API key to <code>.env</code> and
          restart the API.
        </div>
      )}

      <div className="main">
        {/* ---------------- left: conversation ---------------- */}
        <div className="col">
          <div className="tabs">
            <button className="tab active">Conversation</button>
            <div style={{ flex: 1 }} />
            <button
              className="tab"
              disabled={busy === "sweep"}
              onClick={() =>
                runAction("sweep", () => api.sweep(66), (r) => {
                  const res = r as { investigated: number };
                  setNotice(`Investigated ${res.investigated} questions against the corpus.`);
                })
              }
            >
              {busy === "sweep" ? "Investigating all…" : "Investigate all 66"}
            </button>
            <button
              className="tab"
              disabled={busy === "conf"}
              onClick={() =>
                runAction("conf", () => api.detectConflicts(), (r) => {
                  const res = r as { conflicts: Conflict[]; probes_run: number };
                  setNotice(
                    `${res.conflicts.length} of ${res.probes_run} conflict probes fired across sources.`,
                  );
                  setTab("conflicts");
                })
              }
            >
              Detect conflicts
            </button>
          </div>

          <div className="scroll">
            <VoicePanel onTurn={onVoiceTurn} onActivity={refresh} />

            {priorities.length > 0 && (
              <div className="voice-panel">
                <div className="section-title">Most important open questions</div>
                {priorities.slice(0, 3).map((p) => (
                  <div className="row" key={p.question_id} style={{ padding: "4px 0" }}>
                    <span className="qid">{p.question_id}</span>
                    <span style={{ flex: 1, fontSize: 12.5 }}>{p.followup || p.question}</span>
                    {p.criticality && <span className="chip high">{p.criticality}</span>}
                    <Chip status={p.status} />
                    <button onClick={() => send(p.followup || p.question)}>Ask</button>
                  </div>
                ))}
              </div>
            )}

            {messages.length === 0 && (
              <div className="empty">
                Ask the analyst a security question, or start the voice interview. It searches your
                company's documents before it asks you anything.
              </div>
            )}

            {messages.map((m, i) => (
              <div className={`msg ${m.role}`} key={i}>
                <div className="who">
                  {m.role === "user" ? "You" : "AI Security Analyst"}
                  {m.channel === "voice" && <span className="voice-tag">voice</span>}
                </div>
                <div className="bubble">{m.content}</div>
                {m.recorded && m.recorded.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {m.recorded.map((r) => (
                      <div className="hint" key={r.question_id} style={{ color: "var(--confirmed)" }}>
                        {r.was_correction ? "Updated" : "Recorded"} answer for question{" "}
                        {r.question_id}: {r.answer}
                      </div>
                    ))}
                  </div>
                )}
                {m.evidence && m.evidence.length > 0 && (
                  <div style={{ marginTop: 7 }}>
                    {m.evidence.map((ev, j) => (
                      <EvidenceCard key={j} ev={ev} />
                    ))}
                  </div>
                )}
              </div>
            ))}
            <div ref={chatEnd} />
          </div>

          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} disabled={busy === "chat"}>
                {s}
              </button>
            ))}
          </div>
          <div className="composer">
            <textarea
              rows={2}
              placeholder="Answer the analyst, or ask about a control…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
            />
            <button className="primary" disabled={busy === "chat" || !input.trim()} onClick={() => send(input)}>
              {busy === "chat" ? "…" : "Send"}
            </button>
          </div>
        </div>

        {/* ---------------- right: profile ---------------- */}
        <div className="col">
          <div className="tabs">
            {(
              [
                ["questionnaire", "Questionnaire", answers.length],
                ["conflicts", "Conflicts", openConflicts.length],
                ["evidence", "Evidence search", null],
                ["memory", "Memory", facts.length],
                ["prism", "PRISM", health?.prism.sent ?? 0],
              ] as [Tab, string, number | null][]
            ).map(([key, label, count]) => (
              <button
                key={key}
                className={`tab ${tab === key ? "active" : ""}`}
                onClick={() => setTab(key)}
              >
                {label}
                {count !== null && <span className="count">{count}</span>}
              </button>
            ))}
          </div>

          <div className="scroll">
            {tab === "questionnaire" && (
              <>
                <div className="section-title">Completion by topic</div>
                <TopicBreakdown answers={answers} />

                <div className="section-title" style={{ marginTop: 18 }}>
                  Questions
                </div>
                <div className="row" style={{ marginBottom: 10 }}>
                  {(["all", "conflict", "unknown", "verified", "user_confirmed"] as const).map((f) => (
                    <button
                      key={f}
                      className={filter === f ? "primary" : ""}
                      onClick={() => setFilter(f)}
                    >
                      {f === "all" ? "All" : f.replace("_", " ")}
                    </button>
                  ))}
                  <span style={{ flex: 1 }} />
                  <button
                    disabled={busy === "xlsx"}
                    onClick={() =>
                      runAction("xlsx", () => api.exportWorkbook(), (r) => {
                        const res = r as { download: string; file: string };
                        window.open(res.download, "_blank");
                        setNotice(`Filled the organizer's workbook: ${res.file}`);
                      })
                    }
                  >
                    Export workbook
                  </button>
                  <button
                    disabled={busy === "md"}
                    onClick={() =>
                      runAction("md", () => api.exportReport(), (r) => {
                        const res = r as { download: string; file: string };
                        window.open(res.download, "_blank");
                        setNotice(`Wrote trust report: ${res.file}`);
                      })
                    }
                  >
                    Export report
                  </button>
                </div>

                {visible.length === 0 ? (
                  <div className="empty">No questions with this status.</div>
                ) : (
                  visible.map((a) => (
                    <QuestionCard
                      key={a.question_id}
                      answer={a}
                      onInvestigate={investigate}
                      busy={busy === `q-${a.question_id}`}
                    />
                  ))
                )}
              </>
            )}

            {tab === "conflicts" && (
              <>
                <div className="section-title">
                  Contradictions across sources
                  <button
                    disabled={busy === "conf2"}
                    onClick={() => runAction("conf2", () => api.detectConflicts())}
                  >
                    Re-run probes
                  </button>
                </div>
                {conflicts.length === 0 ? (
                  <div className="empty">
                    No conflicts detected yet. Run the probes to compare policy claims against the
                    assessment reports and infrastructure records.
                  </div>
                ) : (
                  conflicts.map((c) => (
                    <ConflictCard
                      key={c.id}
                      conflict={c}
                      onResolve={(id, resolution) =>
                        runAction(`r-${id}`, () => api.resolveConflict(id, resolution))
                      }
                      onAsk={(text) => send(text)}
                    />
                  ))
                )}
              </>
            )}

            {tab === "evidence" && (
              <>
                <div className="section-title">Search the company corpus directly</div>
                <div className="row" style={{ marginBottom: 12 }}>
                  <input
                    placeholder="e.g. production database backup retention"
                    value={searchQ}
                    onChange={(e) => setSearchQ(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && searchQ.trim())
                        runAction("search", () => api.search(searchQ.trim()), (r) =>
                          setSearchHits((r as { hits: Evidence[] }).hits),
                        );
                    }}
                  />
                  <button
                    className="primary"
                    disabled={!searchQ.trim() || busy === "search"}
                    onClick={() =>
                      runAction("search", () => api.search(searchQ.trim()), (r) =>
                        setSearchHits((r as { hits: Evidence[] }).hits),
                      )
                    }
                  >
                    Search
                  </button>
                </div>
                {searchHits.length === 0 ? (
                  <div className="empty">
                    This is the same index the analyst searches before it asks you anything.
                  </div>
                ) : (
                  searchHits.map((h, i) => <EvidenceCard key={i} ev={h} />)
                )}
              </>
            )}

            {tab === "memory" && (
              <>
                <div className="section-title">Facts learned from people</div>
                {facts.length === 0 ? (
                  <div className="empty">
                    Nothing yet. Anything an employee tells the analyst is stored here and reused, so
                    it never asks the same thing twice.
                  </div>
                ) : (
                  facts.map((f) => (
                    <div className="card" key={f.id}>
                      <div className="card-head user_confirmed" style={{ cursor: "default" }}>
                        <span className="qtext">
                          <strong>{f.subject}</strong> — {f.statement}
                        </span>
                        <span className="chip ctrl">{f.actor}</span>
                      </div>
                    </div>
                  ))
                )}
                <div className="section-title" style={{ marginTop: 18 }}>
                  Answers confirmed by a human
                </div>
                {answers.filter((a) => a.status === "user_confirmed").length === 0 ? (
                  <div className="empty">None yet.</div>
                ) : (
                  answers
                    .filter((a) => a.status === "user_confirmed")
                    .map((a) => (
                      <div className="card" key={a.question_id}>
                        <div className="card-head user_confirmed" style={{ cursor: "default" }}>
                          <span className="qid">{a.question_id}</span>
                          <span className="qtext">{a.answer}</span>
                          <Confidence value={a.confidence} />
                        </div>
                      </div>
                    ))
                )}
              </>
            )}

            {tab === "prism" && (
              <>
                <div className="section-title">PRISM by Block Convey — observability</div>
                <div className="voice-panel">
                  <div className="row">
                    <span className={`orb ${health?.prism.configured ? "speaking" : ""}`} />
                    <strong style={{ fontSize: 13 }}>
                      {health?.prism.configured ? "Streaming traces" : "Not configured"}
                    </strong>
                    <span style={{ flex: 1 }} />
                    <span className="chip ctrl">sent {health?.prism.sent ?? 0}</span>
                    <span className="chip ctrl">failed {health?.prism.failed ?? 0}</span>
                    <span className="chip ctrl">skipped {health?.prism.skipped ?? 0}</span>
                  </div>
                  <div className="hint">
                    Every retrieval, decision, conflict probe, voice tool call and human correction is
                    emitted as a PRISM trace on one session id, so the whole investigation is
                    reviewable as a single trajectory. Set the PRISM keys in <code>.env</code> to
                    stream to your project.
                  </div>
                </div>
                <div className="section-title">Recent trace emissions</div>
                {traces.length === 0 ? (
                  <div className="empty">No trace attempts yet.</div>
                ) : (
                  traces.map((t, i) => (
                    <div className="trace" key={i}>
                      <span
                        className="sq"
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: 2,
                          background: t.ok ? "var(--verified)" : "var(--unknown)",
                        }}
                      />
                      <span className="step">{t.step}</span>
                      <span className="st">{String(t.status)}</span>
                    </div>
                  ))
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ConversationProvider clientTools={voiceClientTools}>
      <Inner />
    </ConversationProvider>
  );
}
