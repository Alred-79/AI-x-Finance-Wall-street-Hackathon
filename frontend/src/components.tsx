import { useState } from "react";
import type { Answer, Conflict, Evidence, Stats, Status } from "./api";

export const STATUS_LABEL: Record<Status, string> = {
  verified: "Verified from documents",
  user_confirmed: "Confirmed by employee",
  conflict: "Conflict",
  unknown: "Unknown",
};

export const STATUS_COLOR: Record<Status, string> = {
  verified: "var(--verified)",
  user_confirmed: "var(--confirmed)",
  conflict: "var(--conflict)",
  unknown: "var(--unknown)",
};

const ORDER: Status[] = ["verified", "user_confirmed", "conflict", "unknown"];

export function Chip({ status }: { status: Status }) {
  return <span className={`chip ${status}`}>{STATUS_LABEL[status]}</span>;
}

export function Confidence({ value }: { value: number }) {
  const color =
    value >= 0.8 ? "var(--verified)" : value >= 0.5 ? "var(--unknown)" : "var(--conflict)";
  return (
    <div className="conf" title="Confidence that an auditor would accept this answer as supported">
      <div className="track">
        <i style={{ width: `${Math.round(value * 100)}%`, background: color }} />
      </div>
      <span className="num">{value.toFixed(2)}</span>
    </div>
  );
}

export function ProgressBar({ stats }: { stats: Stats }) {
  const total = stats.total_questions || 1;
  return (
    <div className="progress-wrap">
      <div className="progress-bar" title="Answer status across the questionnaire">
        {ORDER.map((s) => {
          const n = stats.by_status[s] ?? 0;
          return n > 0 ? (
            <i
              key={s}
              style={{ width: `${(100 * n) / total}%`, background: STATUS_COLOR[s] }}
              title={`${STATUS_LABEL[s]}: ${n}`}
            />
          ) : null;
        })}
      </div>
      <span className="progress-num">{stats.completion_pct}%</span>
    </div>
  );
}

export function Legend({ stats }: { stats: Stats }) {
  return (
    <div className="legend">
      {ORDER.map((s) => (
        <div className="item" key={s}>
          <span className="sq" style={{ background: STATUS_COLOR[s] }} />
          {STATUS_LABEL[s]}
          <strong style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>
            {stats.by_status[s] ?? 0}
          </strong>
        </div>
      ))}
    </div>
  );
}

export function EvidenceCard({ ev }: { ev: Evidence }) {
  const [open, setOpen] = useState(false);
  const unreadable = ev.kind === "image_unread";
  const notProof = ev.source_category === "questionnaire";
  return (
    <div className={`evidence ${open ? "expanded" : ""}`} onClick={() => setOpen(!open)}>
      <div className="cite">{ev.citation}</div>
      <div className="quote">{ev.text}</div>
      <div className="meta">
        <span className="cat">{ev.source_category.replace(/_/g, " ")}</span>
        {unreadable && (
          <span className="cat" style={{ color: "var(--unknown)", borderColor: "#3d3620" }}>
            image not machine-read
          </span>
        )}
        {notProof && (
          <span className="cat" style={{ color: "var(--unknown)", borderColor: "#3d3620" }}>
            blank form — not proof
          </span>
        )}
        {typeof ev.score === "number" && ev.score > 0 && (
          <span className="cat" style={{ fontFamily: "var(--mono)" }}>
            score {ev.score.toFixed(1)}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span className="cat" style={{ border: "none" }}>
          {open ? "collapse" : "expand"}
        </span>
      </div>
    </div>
  );
}

export function QuestionCard({
  answer,
  onInvestigate,
  busy,
}: {
  answer: Answer;
  onInvestigate: (id: string, force: boolean) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const critical = /high|critical/i.test(answer.criticality);
  return (
    <div className="card">
      <div className={`card-head ${answer.status}`} onClick={() => setOpen(!open)}>
        <span className="qid">{answer.question_id}</span>
        <span className="qtext">{answer.question}</span>
        {answer.control_id && <span className="chip ctrl">{answer.control_id}</span>}
        {critical && <span className="chip high">{answer.criticality}</span>}
        <Chip status={answer.status} />
      </div>
      {open && (
        <div className="card-body">
          {answer.answer && (
            <div className="kv">
              <div className="k">Answer</div>
              <div className="v">{answer.answer}</div>
            </div>
          )}
          {answer.rationale && (
            <div className="kv">
              <div className="k">Reasoning</div>
              <div className="v" style={{ color: "var(--muted)" }}>
                {answer.rationale}
              </div>
            </div>
          )}
          {answer.followup && (
            <div className="kv">
              <div className="k">Follow-up needed</div>
              <div className="v" style={{ color: "var(--unknown)" }}>
                {answer.followup}
              </div>
            </div>
          )}
          {answer.control_objective && (
            <div className="kv">
              <div className="k">Control objective — {answer.control_id}</div>
              <div className="v" style={{ color: "var(--muted)", fontSize: 12 }}>
                {answer.control_objective}
              </div>
            </div>
          )}
          <div className="kv">
            <div className="k">Evidence ({answer.evidence.length})</div>
            {answer.evidence.length === 0 ? (
              <div className="v" style={{ color: "var(--dim)", fontSize: 12 }}>
                No evidence cited. This answer is not claimed as verified.
              </div>
            ) : (
              answer.evidence.map((ev, i) => <EvidenceCard key={i} ev={ev} />)
            )}
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <Confidence value={answer.confidence} />
            <span style={{ flex: 1 }} />
            <button
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                onInvestigate(answer.question_id, true);
              }}
            >
              {busy ? "Investigating…" : "Re-investigate"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ConflictCard({
  conflict,
  onResolve,
  onAsk,
}: {
  conflict: Conflict;
  onResolve: (id: string, resolution: string) => void;
  onAsk: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const resolved = conflict.status === "resolved";
  return (
    <div className="conflict-card">
      <div className="top">
        <div className="row" style={{ marginBottom: 6 }}>
          <span className={`chip ${resolved ? "verified" : "conflict"}`}>
            {resolved ? "resolved" : `${conflict.severity} severity`}
          </span>
          {conflict.topic && <span className="chip ctrl">{conflict.topic}</span>}
          <span style={{ flex: 1 }} />
          <span className="chip ctrl">{conflict.detected_by}</span>
        </div>
        <div className="sum">{conflict.summary}</div>
        <div className="side">
          <div className="lbl">Stated</div>
          <div className="txt">{conflict.side_a}</div>
        </div>
        <div className="side">
          <div className="lbl">Observed</div>
          <div className="txt">{conflict.side_b}</div>
        </div>
        {resolved ? (
          <div className="side">
            <div className="lbl">Resolution</div>
            <div className="txt resolved-tag">{conflict.resolution}</div>
          </div>
        ) : (
          <>
            {conflict.question_hint && (
              <div className="side">
                <div className="lbl">Ask</div>
                <div className="txt" style={{ color: "var(--unknown)" }}>
                  {conflict.question_hint}
                </div>
              </div>
            )}
            <div className="row" style={{ marginTop: 10 }}>
              <input
                placeholder="How is this actually resolved?"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && text.trim()) onResolve(conflict.id, text.trim());
                }}
              />
              <button
                className="primary"
                disabled={!text.trim()}
                onClick={() => onResolve(conflict.id, text.trim())}
              >
                Resolve
              </button>
              {conflict.question_hint && (
                <button onClick={() => onAsk(conflict.question_hint!)}>Ask analyst</button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function TopicBreakdown({ answers }: { answers: Answer[] }) {
  const topics = Array.from(new Set(answers.map((a) => a.topic))).sort();
  return (
    <div>
      {topics.map((topic) => {
        const rows = answers.filter((a) => a.topic === topic);
        const counts = ORDER.map((s) => rows.filter((r) => r.status === s).length);
        const done = counts[0] + counts[1];
        return (
          <div className="topic-row" key={topic}>
            <span>{topic}</span>
            <div className="bars" title={`${done} of ${rows.length} answered`}>
              {ORDER.map((s, i) =>
                counts[i] > 0 ? (
                  <i
                    key={s}
                    style={{
                      width: `${(100 * counts[i]) / rows.length}%`,
                      background: STATUS_COLOR[s],
                    }}
                    title={`${STATUS_LABEL[s]}: ${counts[i]}`}
                  />
                ) : null,
              )}
            </div>
            <span className="n">
              {done}/{rows.length}
            </span>
          </div>
        );
      })}
    </div>
  );
}
