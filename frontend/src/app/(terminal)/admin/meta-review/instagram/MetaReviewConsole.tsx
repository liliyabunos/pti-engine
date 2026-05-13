"use client";

import { useState } from "react";

interface IGStatus {
  configured: boolean;
  ig_business_account_id?: string;
  username?: string;
  error?: string;
}

const DEMO_HASHTAGS = [
  "perfume",
  "fragrance",
  "nicheperfume",
  "fragrancecommunity",
  "perfumereview",
  "scentsoftheday",
] as const;
type DemoHashtag = (typeof DEMO_HASHTAGS)[number];

export function MetaReviewConsole() {
  const [status, setStatus] = useState<IGStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [selectedHashtag, setSelectedHashtag] = useState<DemoHashtag>("perfume");

  // ── Diagnostic state ────────────────────────────────────────────────────────
  const [demoDebugStatus, setDemoDebugStatus] = useState<string | null>(null);
  const [demoDebugPayload, setDemoDebugPayload] = useState<string | null>(null);

  async function checkStatus() {
    setLoadingStatus(true);
    setStatus(null);
    try {
      const resp = await fetch("/api/admin/instagram-review?action=status");
      const data = await resp.json();
      setStatus(data);
    } catch {
      setStatus({ configured: false, error: "Could not reach backend." });
    } finally {
      setLoadingStatus(false);
    }
  }

  async function runDemo() {
    // Step 1 — handler fired
    setDemoDebugStatus("CLICKED — handler running");
    setDemoDebugPayload(null);

    const url = `/api/admin/instagram-review?action=demo&hashtag=${encodeURIComponent(selectedHashtag)}`;

    let httpStatus: number | null = null;
    let ok: boolean | null = null;
    let bodyText = "";

    try {
      const resp = await fetch(url);
      httpStatus = resp.status;
      ok = resp.ok;

      // Step 2 — response received, try to get body
      try {
        bodyText = await resp.text();
      } catch {
        bodyText = "(could not read response body)";
      }
    } catch (err) {
      bodyText = `fetch() threw: ${err instanceof Error ? err.message : String(err)}`;
    }

    // Step 3 — try JSON parse for display
    let parsedDisplay: unknown = null;
    try {
      parsedDisplay = JSON.parse(bodyText);
    } catch {
      parsedDisplay = null;
    }

    setDemoDebugStatus(
      `RESPONSE RECEIVED — HTTP ${httpStatus ?? "?"} — ok=${ok ?? "?"}`
    );
    setDemoDebugPayload(
      parsedDisplay !== null
        ? JSON.stringify(parsedDisplay, null, 2)
        : `(raw text)\n${bodyText}`
    );
  }

  return (
    <div style={{ maxWidth: 768, margin: "0 auto", padding: "40px 24px", fontFamily: "monospace" }}>
      {/* Header */}
      <p style={{ fontSize: 10, color: "#f59e0b", textTransform: "uppercase", letterSpacing: 2, marginBottom: 4 }}>
        Admin · Meta App Review
      </p>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: "#f4f4f5", marginBottom: 8 }}>
        Instagram Public Content — App Review Demo
      </h1>

      {/* Step 1 — Connection */}
      <div style={{ marginTop: 32, marginBottom: 32 }}>
        <button
          onClick={checkStatus}
          disabled={loadingStatus}
          style={{
            border: "1px solid #52525b",
            borderRadius: 4,
            padding: "6px 12px",
            fontSize: 12,
            color: "#d4d4d8",
            background: "transparent",
            cursor: "pointer",
          }}
        >
          {loadingStatus ? "Checking…" : "Check Connection"}
        </button>

        {status && (
          <pre style={{
            marginTop: 12,
            padding: 12,
            background: status.configured ? "#052e16" : "#431407",
            border: `1px solid ${status.configured ? "#166534" : "#7c2d12"}`,
            borderRadius: 4,
            fontSize: 11,
            color: status.configured ? "#86efac" : "#fdba74",
            whiteSpace: "pre-wrap",
          }}>
            {JSON.stringify(status, null, 2)}
          </pre>
        )}
      </div>

      {/* Step 2 — Hashtag demo */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <select
            value={selectedHashtag}
            onChange={(e) => setSelectedHashtag(e.target.value as DemoHashtag)}
            style={{
              border: "1px solid #3f3f46",
              borderRadius: 4,
              padding: "6px 12px",
              fontSize: 12,
              color: "#e4e4e7",
              background: "#18181b",
            }}
          >
            {DEMO_HASHTAGS.map((tag) => (
              <option key={tag} value={tag}>#{tag}</option>
            ))}
          </select>

          <button
            onClick={runDemo}
            style={{
              border: "1px solid #d97706",
              borderRadius: 4,
              padding: "6px 16px",
              fontSize: 12,
              color: "#fbbf24",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            Run Hashtag Demo
          </button>
        </div>

        {/* ── DIAGNOSTIC BLOCK — no abstraction, no component, plain inline ── */}
        {demoDebugStatus !== null && (
          <div
            style={{
              marginTop: 16,
              padding: 16,
              background: "#0c0a09",
              border: "2px solid #d97706",
              borderRadius: 6,
            }}
          >
            <p style={{ fontSize: 11, color: "#f59e0b", fontWeight: 700, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
              DIAGNOSTIC
            </p>
            <p style={{ fontSize: 12, color: "#fde68a", marginBottom: demoDebugPayload ? 12 : 0 }}>
              {demoDebugStatus}
            </p>
            {demoDebugPayload && (
              <pre style={{
                fontSize: 11,
                color: "#d4d4d8",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                margin: 0,
                maxHeight: 400,
                overflowY: "auto",
              }}>
                {demoDebugPayload}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
