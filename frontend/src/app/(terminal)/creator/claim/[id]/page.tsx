"use client";

/**
 * C2 — Creator Profile Claim Page.
 *
 * Auth: protected by (terminal) layout + middleware — unauthenticated users
 * are redirected to /login?next=/creator/claim/[id].
 *
 * Claim submission goes through /api/creator-claims (Next.js server route)
 * which reads the Supabase session server-side and forwards with a verified
 * user_id header. Browser never sends user_id directly to the backend.
 *
 * No OAuth. No platform API access. No private data requested.
 */

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BadgeCheck, Copy, ExternalLink } from "lucide-react";

import { fetchCreatorProfile } from "@/lib/api/creators";
import {
  fetchMyClaims,
  submitClaim,
  type ClaimResponse,
  type ClaimSummary,
} from "@/lib/api/creator_claims";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";

// ---------------------------------------------------------------------------
// Disclaimer block — required by revision 7
// ---------------------------------------------------------------------------

function ClaimDisclaimer() {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-[11px] leading-relaxed text-zinc-500 space-y-1">
      <p>
        Verification confirms that you control this public creator account. It
        does not grant FragranceIndex.ai access to your private account.
      </p>
      <p>No OAuth or password is required or requested.</p>
      <p>
        FragranceIndex.ai is not affiliated with YouTube, TikTok, Instagram,
        Reddit, or other platforms.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Copy-to-clipboard button
// ---------------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="inline-flex items-center gap-1 rounded border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-400 hover:text-zinc-200 transition-colors"
    >
      <Copy size={9} />
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Status panels
// ---------------------------------------------------------------------------

function PendingPanel({ claim }: { claim: ClaimSummary }) {
  return (
    <TerminalPanel>
      <div className="space-y-3 px-5 py-5">
        <p className="text-sm font-semibold text-zinc-200">
          Your claim is under review
        </p>
        <p className="text-[12px] text-zinc-500">
          Method:{" "}
          <span className="text-zinc-400">
            {claim.claim_method === "bio_code"
              ? "Bio-code verification"
              : claim.claim_method === "screenshot"
              ? "Screenshot / link"
              : "Manual review"}
          </span>
        </p>
        {claim.claimed_at && (
          <p className="text-[12px] text-zinc-500">
            Submitted:{" "}
            <span className="text-zinc-400">
              {claim.claimed_at.slice(0, 10)}
            </span>
          </p>
        )}
        {claim.evidence_url && (
          <p className="text-[12px] text-zinc-500">
            Evidence:{" "}
            <a
              href={claim.evidence_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
            >
              {claim.evidence_url}
              <ExternalLink size={10} />
            </a>
          </p>
        )}
        <p className="text-[12px] text-zinc-600">
          We will verify the public evidence you provided. No account access is
          required.
        </p>
      </div>
    </TerminalPanel>
  );
}

function VerifiedPanel() {
  return (
    <TerminalPanel>
      <div className="flex items-center gap-2 px-5 py-5">
        <BadgeCheck size={16} className="text-emerald-400 shrink-0" />
        <p className="text-sm font-semibold text-emerald-400">
          Profile Verified
        </p>
      </div>
      <p className="px-5 pb-5 text-[12px] text-zinc-500">
        This profile is verified. No further action is needed.
      </p>
    </TerminalPanel>
  );
}

function RejectedPanel({
  claim,
  onResubmit,
}: {
  claim: ClaimSummary;
  onResubmit: () => void;
}) {
  return (
    <TerminalPanel>
      <div className="space-y-3 px-5 py-5">
        <p className="text-sm font-semibold text-red-400">Claim Not Approved</p>
        {claim.rejection_reason && (
          <p className="text-[12px] text-zinc-500">
            Reason:{" "}
            <span className="text-zinc-400">{claim.rejection_reason}</span>
          </p>
        )}
        <p className="text-[12px] text-zinc-500">
          Questions? Contact{" "}
          <a
            href="mailto:support@fragranceindex.ai"
            className="text-amber-400 hover:underline"
          >
            support@fragranceindex.ai
          </a>
          .
        </p>
        <button
          onClick={onResubmit}
          className="mt-1 inline-flex items-center rounded border border-zinc-700/60 bg-zinc-800/40 px-3 py-1.5 text-[12px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
        >
          Submit a New Claim
        </button>
      </div>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Success panel (shown after successful submission)
// ---------------------------------------------------------------------------

function SuccessPanel({
  result,
  onDone,
}: {
  result: ClaimResponse;
  onDone: () => void;
}) {
  return (
    <TerminalPanel>
      <div className="space-y-4 px-5 py-5">
        <p className="text-sm font-semibold text-zinc-200">
          Claim submitted for review
        </p>

        {result.verification_code && (
          <div className="space-y-2">
            <p className="text-[12px] text-zinc-400">
              Your verification code:
            </p>
            <div className="flex items-center gap-2">
              <span className="rounded border border-amber-800/60 bg-amber-950/20 px-3 py-1.5 font-mono text-sm font-bold tracking-widest text-amber-300">
                {result.verification_code}
              </span>
              <CopyButton text={result.verification_code} />
            </div>
            <p className="text-[11px] text-zinc-500">
              Add this code to your public creator profile. Our team will check
              the public evidence at the URL you provided.
            </p>
            {result.verification_code_expires_at && (
              <p className="text-[10px] text-zinc-700">
                Code expires:{" "}
                {result.verification_code_expires_at.slice(0, 10)}
              </p>
            )}
          </div>
        )}

        {!result.verification_code && (
          <p className="text-[12px] text-zinc-500">
            Our team will review the public evidence you provided. No account
            access is required.
          </p>
        )}

        <button
          onClick={onDone}
          className="inline-flex items-center gap-1.5 rounded border border-zinc-700/60 bg-zinc-800/40 px-3 py-1.5 text-[12px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
        >
          Done
        </button>
      </div>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Claim form
// ---------------------------------------------------------------------------

type ClaimMethod = "bio_code" | "manual_review";

function ClaimForm({
  platform,
  creatorId,
  onSuccess,
}: {
  platform: string;
  creatorId: string;
  onSuccess: (result: ClaimResponse) => void;
}) {
  const [method, setMethod] = useState<ClaimMethod>("bio_code");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isValidUrl =
    evidenceUrl.trim().startsWith("http://") ||
    evidenceUrl.trim().startsWith("https://");
  const canSubmit = isValidUrl && !submitting;

  const platformLabel =
    platform === "youtube"
      ? "YouTube channel description"
      : platform === "tiktok"
      ? "TikTok bio"
      : platform === "instagram"
      ? "Instagram bio"
      : platform === "reddit"
      ? "Reddit profile"
      : "public creator profile";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setErrorMsg(null);

    try {
      const result = await submitClaim({
        platform,
        creator_id: creatorId,
        claim_method: method,
        evidence_url: evidenceUrl.trim(),
        note: note.trim() || undefined,
      });
      onSuccess(result);
    } catch (err: unknown) {
      const e = err as Error & { status?: number };
      if (e.status === 409) {
        setErrorMsg(
          "You already have an active claim for this profile. Refresh the page to see its status."
        );
      } else {
        setErrorMsg(e.message ?? "Submission failed. Please try again.");
      }
      setSubmitting(false);
    }
  }

  return (
    <TerminalPanel noPad>
      {/* Method tabs */}
      <div className="flex border-b border-zinc-800">
        {(["bio_code", "manual_review"] as ClaimMethod[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMethod(m)}
            className={`px-4 py-2.5 text-[11px] font-medium transition-colors ${
              method === m
                ? "border-b-2 border-amber-500 text-amber-300"
                : "text-zinc-600 hover:text-zinc-400"
            }`}
          >
            {m === "bio_code" ? "Bio-Code Verification" : "Manual Review"}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="space-y-5 px-5 py-5">
        {/* Method-specific instructions */}
        {method === "bio_code" ? (
          <div className="space-y-2 rounded border border-zinc-800 bg-zinc-900/30 px-4 py-3">
            <p className="text-[11px] font-semibold text-zinc-300">
              How bio-code verification works:
            </p>
            <ol className="list-decimal list-inside space-y-1 text-[11px] text-zinc-500">
              <li>Submit this form with your public profile URL.</li>
              <li>
                A unique verification code will be shown on the next screen.
              </li>
              <li>
                Add the code to your{" "}
                <span className="text-zinc-400">{platformLabel}</span>.
              </li>
              <li>
                Our team will confirm the code appears publicly during review.
              </li>
            </ol>
          </div>
        ) : (
          <div className="rounded border border-zinc-800 bg-zinc-900/30 px-4 py-3 text-[11px] text-zinc-500">
            Submit a public URL showing your association with this creator
            account. Our team will review the evidence manually. Do not submit
            private screenshots, DMs, or login credentials.
          </div>
        )}

        {/* Evidence URL */}
        <div className="space-y-1.5">
          <label className="block text-[11px] font-medium text-zinc-400">
            {method === "bio_code"
              ? "Your public creator profile URL"
              : "Public evidence URL"}
            <span className="ml-1 text-red-400">*</span>
          </label>
          <input
            type="url"
            required
            value={evidenceUrl}
            onChange={(e) => setEvidenceUrl(e.target.value)}
            placeholder="https://..."
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none focus:border-zinc-500"
          />
          <p className="text-[10px] text-zinc-700">
            Must be a public http/https URL. Do not submit pages that require login.
          </p>
        </div>

        {/* Optional note */}
        <div className="space-y-1.5">
          <label className="block text-[11px] font-medium text-zinc-400">
            Optional note
          </label>
          <textarea
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Additional context for the reviewer..."
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none focus:border-zinc-500 resize-none"
          />
        </div>

        {/* Error */}
        {errorMsg && (
          <p className="rounded border border-red-900/50 bg-red-950/20 px-3 py-2 text-[11px] text-red-400">
            {errorMsg}
          </p>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex items-center rounded border border-amber-800/60 bg-amber-950/30 px-4 py-2 text-[12px] font-medium text-amber-300 transition-colors hover:bg-amber-950/50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {submitting ? "Submitting…" : "Submit Verification Request"}
        </button>
      </form>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CreatorClaimPage({ params }: PageProps) {
  const { id } = use(params);
  const creatorId = decodeURIComponent(id);
  const router = useRouter();

  // Creator profile (for display name + platform)
  const [profile, setProfile] = useState<{
    displayName: string;
    platform: string;
    externalUrl: string | null;
  } | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  // Existing claim status for this creator
  const [activeClaim, setActiveClaim] = useState<ClaimSummary | null>(null);
  const [claimsLoading, setClaimsLoading] = useState(true);

  // After successful submission
  const [submitResult, setSubmitResult] = useState<ClaimResponse | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Load creator profile
  useEffect(() => {
    setProfileLoading(true);
    fetchCreatorProfile(creatorId)
      .then((p) => {
        setProfile({
          displayName: p.creator_handle ?? p.title ?? creatorId,
          platform: p.platform ?? "youtube",
          externalUrl: p.external_url,
        });
      })
      .catch(() => {
        setProfile({ displayName: creatorId, platform: "youtube", externalUrl: null });
      })
      .finally(() => setProfileLoading(false));
  }, [creatorId]);

  // Load user's existing claims for this creator
  useEffect(() => {
    setClaimsLoading(true);
    const platform = profile?.platform ?? "youtube";
    fetchMyClaims(platform, creatorId)
      .then((res) => {
        const found = res.claims.find((c) => c.creator_id === creatorId) ?? null;
        setActiveClaim(found);
      })
      .catch(() => setActiveClaim(null))
      .finally(() => setClaimsLoading(false));
  }, [creatorId, profile?.platform]);

  const loading = profileLoading || claimsLoading;

  // Determine what to show
  const pendingOrVerified =
    activeClaim &&
    (activeClaim.claim_status === "pending" ||
      activeClaim.claim_status === "verified");
  const rejected =
    activeClaim && activeClaim.claim_status === "rejected";
  const showClaimForm =
    !submitResult &&
    (showForm || (!pendingOrVerified && !rejected));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Claim Creator Profile"
        subtitle={profile ? `${profile.displayName} · ${profile.platform}` : undefined}
        actions={
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300"
          >
            <ArrowLeft size={12} />
            Back
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-xl space-y-4">
          {/* Creator summary */}
          {profile && (
            <TerminalPanel>
              <div className="px-5 py-4 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
                    {profile.platform}
                  </span>
                  <span className="text-sm font-semibold text-zinc-200">
                    {profile.displayName}
                  </span>
                </div>
                {profile.externalUrl && (
                  <a
                    href={profile.externalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:underline"
                  >
                    {profile.externalUrl}
                    <ExternalLink size={9} />
                  </a>
                )}
              </div>
              <PanelDivider />
              <div className="px-5 py-3">
                <ClaimDisclaimer />
              </div>
            </TerminalPanel>
          )}

          {/* Body */}
          {loading ? (
            <LoadingSkeleton rows={4} rowHeight={24} />
          ) : submitResult ? (
            <SuccessPanel
              result={submitResult}
              onDone={() => router.back()}
            />
          ) : activeClaim?.claim_status === "verified" ? (
            <VerifiedPanel />
          ) : activeClaim?.claim_status === "pending" ? (
            <PendingPanel claim={activeClaim} />
          ) : rejected && !showForm ? (
            <RejectedPanel
              claim={activeClaim!}
              onResubmit={() => setShowForm(true)}
            />
          ) : showClaimForm ? (
            <ClaimForm
              platform={profile?.platform ?? "youtube"}
              creatorId={creatorId}
              onSuccess={(result) => {
                setSubmitResult(result);
                setShowForm(false);
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
