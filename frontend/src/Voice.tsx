/**
 * ElevenLabs voice interface.
 *
 * The voice agent is not a separate assistant — it shares this project's brain.
 * Client tools call back into our own API so a spoken conversation reads the same
 * evidence index and writes to the same persistent security profile as the text
 * chat. Ask a question by voice, and the answer appears in the questionnaire.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  useConversationControls,
  useConversationMode,
  useConversationStatus,
} from "@elevenlabs/react";
import { api } from "./api";

export interface VoiceEvent {
  role: "user" | "assistant";
  content: string;
}

const TOOL_ENDPOINT = "/api/voice/tool";

async function callTool(body: Record<string, unknown>) {
  const res = await fetch(TOOL_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return { error: await res.text() };
  return res.json();
}

/** Client tools registered with the ElevenLabs agent. */
export const voiceClientTools = {
  /** Search the company corpus. The agent must call this BEFORE asking the human. */
  searchCompanyEvidence: async ({ query }: { query: string }) =>
    JSON.stringify(await callTool({ tool: "search_company_evidence", query })),

  /** Which question matters most right now. */
  getNextQuestion: async () => JSON.stringify(await callTool({ tool: "get_next_question" })),

  /** Persist what the employee just confirmed. */
  recordAnswer: async ({ question_id, answer }: { question_id: string; answer: string }) =>
    JSON.stringify(
      await callTool({ tool: "record_answer", question_id, answer, speaker: "employee (voice)" }),
    ),

  /** Persist a standalone fact worth remembering. */
  recordFact: async ({ subject, statement }: { subject: string; statement: string }) =>
    JSON.stringify(
      await callTool({ tool: "record_fact", subject, statement, speaker: "employee (voice)" }),
    ),

  /** Read out the contradictions found across company sources. */
  getOpenConflicts: async () => JSON.stringify(await callTool({ tool: "get_open_conflicts" })),

  /** Close a conflict with what the employee said is actually true. */
  resolveConflict: async ({
    conflict_id,
    resolution,
  }: {
    conflict_id: string;
    resolution: string;
  }) =>
    JSON.stringify(
      await callTool({
        tool: "resolve_conflict",
        question_id: conflict_id,
        statement: resolution,
        speaker: "employee (voice)",
      }),
    ),
};

export function VoicePanel({
  onTurn,
  onActivity,
}: {
  onTurn: (event: VoiceEvent) => void;
  onActivity: () => void;
}) {
  const { startSession, endSession } = useConversationControls();
  const { status, message } = useConversationStatus();
  const { isSpeaking, isListening } = useConversationMode();
  const [config, setConfig] = useState<{ enabled: boolean; agent_id: string; has_api_key: boolean }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const turnRef = useRef(onTurn);
  turnRef.current = onTurn;

  useEffect(() => {
    api.voiceConfig().then(setConfig).catch(() => setConfig({ enabled: false, agent_id: "", has_api_key: false }));
  }, []);

  const connected = status === "connected";

  const start = useCallback(async () => {
    setError(undefined);
    setBusy(true);
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      // Prefer a server-minted token so the API key never reaches the browser.
      let token: string | undefined;
      try {
        const res = await api.voiceToken();
        token = res.token;
      } catch {
        token = undefined;
      }
      await startSession(
        token
          ? { conversationToken: token }
          : { agentId: config?.agent_id ?? "" },
      );
      onActivity();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [config?.agent_id, onActivity, startSession]);

  if (!config) {
    return null;
  }

  if (!config.enabled) {
    return (
      <div className="voice-panel">
        <div className="row">
          <span className="orb" />
          <strong style={{ fontSize: 13 }}>Voice interview</strong>
          <span style={{ flex: 1 }} />
          <span className="chip ctrl">not configured</span>
        </div>
        <div className="hint">
          Set <code>ELEVENLABS_AGENT_ID</code> and <code>ELEVENLABS_API_KEY</code> in{" "}
          <code>.env</code>, then restart the API. The voice agent shares this project's evidence
          index and security profile through the tools in <code>/api/voice/tool</code>.
        </div>
      </div>
    );
  }

  return (
    <div className="voice-panel">
      <div className="row">
        <span className={`orb ${isSpeaking ? "speaking" : isListening ? "listening" : ""}`} />
        <strong style={{ fontSize: 13 }}>Voice interview</strong>
        <span className="chip ctrl">
          {connected ? (isSpeaking ? "analyst speaking" : "listening") : status}
        </span>
        <span style={{ flex: 1 }} />
        {connected ? (
          <button className="danger" onClick={() => endSession()}>
            End call
          </button>
        ) : (
          <button className="live" disabled={busy} onClick={start}>
            {busy ? "Connecting…" : "Start voice interview"}
          </button>
        )}
      </div>
      <div className="hint">
        Speak to the analyst. It searches your documents before it asks you anything, and everything
        it learns lands in the same questionnaire on the right.
      </div>
      {(error || message) && (
        <div className="hint" style={{ color: "var(--conflict)" }}>
          {error || message}
        </div>
      )}
    </div>
  );
}
