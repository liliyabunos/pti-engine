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
import Link from "next/link";
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
// How to claim — help text above form
// ---------------------------------------------------------------------------

function HowToClaim({ platform }: { platform: string }) {
  const bioLocation =
    platform === "youtube"
      ? "YouTube channel description (About tab)"
      : platform === "tiktok"
      ? "TikTok bio"
      : platform === "instagram"
      ? "Instagram bio"
      : platform === "reddit"
      ? "Reddit profile About section"
      : "your public creator profile";

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/20 px-4 py-4 space-y-3">
      <p className="text-[11px] font-semibold text-zinc-300">
        How profile verification works
      </p>
      <div className="space-y-2 text-[11px] text-zinc-500 leading-relaxed">
        <p>
          <span className="text-zinc-400 font-medium">Bio-code (recommended):</span>{" "}
          Submit your profile URL. You'll receive a unique code — add it to your{" "}
          {bioLocation}. Our team checks the code is publicly visible, then approves
          your claim. Remove the code after verification if you prefer.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Manual review:</span>{" "}
          Submit a public URL that demonstrates your association with this account —
          for example a pinned post, a link from your personal site, or a public
          announcement. Our team reviews and responds within a few business days.
        </p>
      </div>
      <div className="border-t border-zinc-800/60 pt-2 space-y-2">
        <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-wide">
          Not accepted
        </p>
        <ul className="space-y-0.5 text-[10px] text-zinc-700">
          <li>Passwords or login credentials of any kind</li>
          <li>Private messages, DMs, or screenshots of private data</li>
          <li>Pages that require a login or account to view</li>
          <li>Unverifiable name-only claims ("I am The Perfume Guy")</li>
          <li>Accounts on a different platform with the same display name</li>
        </ul>
        <p className="text-[10px] text-zinc-600 pt-0.5">
          No password, OAuth, or platform login is required or requested.
          FragranceIndex.ai is not affiliated with YouTube, TikTok, Instagram, or Reddit.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Disclaimer block
// ---------------------------------------------------------------------------

function ClaimDisclaimer() {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-[11px] leading-relaxed text-zinc-500 space-y-1">
      <p>
        Verification confirms that you control this public creator account. It
        does not grant FragranceIndex.ai access to your private account data.
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
  const methodLabel =
    claim.claim_method === "bio_code"
      ? "Bio-code verification"
      : claim.claim_method === "screenshot"
      ? "Screenshot / link"
      : "Manual review";

  return (
    <TerminalPanel>
      <div className="space-y-3 px-5 py-5">
        <p className="text-sm font-semibold text-zinc-200">
          Claim under review
        </p>
        <p className="text-[12px] text-zinc-500">
          Method: <span className="text-zinc-400">{methodLabel}</span>
        </p>
        {claim.claimed_at && (
          <p className="text-[12px] text-zinc-500">
            Submitted:{" "}
            <span className="text-zinc-400">{claim.claimed_at.slice(0, 10)}</span>
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
        <div className="rounded border border-zinc-800 bg-zinc-900/30 px-3 py-2.5 text-[11px] text-zinc-500 space-y-1">
          {claim.claim_method === "bio_code" ? (
            <p>
              Make sure the verification code is still visible in your public
              profile. Our team will check it is publicly readable before approving.
            </p>
          ) : (
            <p>
              Our team will review the evidence you provided. We aim to respond
              within a few business days.
            </p>
          )}
          <p>
            Questions?{" "}
            <a
              href="mailto:support@fragranceindex.ai"
              className="text-amber-400 hover:underline"
            >
              support@fragranceindex.ai
            </a>
          </p>
        </div>
      </div>
    </TerminalPanel>
  );
}

function VerifiedPanel() {
  return (
    <TerminalPanel>
      <div className="space-y-2 px-5 py-5">
        <div className="flex items-center gap-2">
          <BadgeCheck size={16} className="text-emerald-400 shrink-0" />
          <p className="text-sm font-semibold text-emerald-400">
            Profile Verified
          </p>
        </div>
        <p className="text-[12px] text-zinc-500">
          Your creator profile is verified on FragranceIndex.ai. The verified
          badge is now visible on your public profile page.
        </p>
        <p className="text-[11px] text-zinc-600">
          If you need to update your profile details or have questions, contact{" "}
          <a
            href="mailto:support@fragranceindex.ai"
            className="text-amber-400 hover:underline"
          >
            support@fragranceindex.ai
          </a>
          .
        </p>
      </div>
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

        {claim.rejection_reason ? (
          <div className="rounded border border-red-900/30 bg-red-950/10 px-3 py-2.5 text-[12px] text-zinc-400">
            <span className="block text-[10px] font-semibold uppercase tracking-wide text-red-500/70 mb-1">
              Reason
            </span>
            {claim.rejection_reason}
          </div>
        ) : (
          <p className="text-[12px] text-zinc-500">
            Your claim could not be verified from the evidence provided.
          </p>
        )}

        <div className="text-[11px] text-zinc-500 space-y-1">
          <p>You can submit a new claim with updated or corrected evidence.</p>
          <p>
            Common fixes: make sure the evidence URL is publicly accessible, the
            bio-code is still visible in your profile, or use a different URL
            that clearly shows your association with this account.
          </p>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={onResubmit}
            className="inline-flex items-center rounded border border-zinc-700/60 bg-zinc-800/40 px-3 py-1.5 text-[12px] text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 transition-colors"
          >
            Try Again
          </button>
          <a
            href="mailto:support@fragranceindex.ai"
            className="text-[11px] text-zinc-600 hover:text-amber-400 transition-colors"
          >
            Contact support
          </a>
        </div>
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

        <p className="text-[11px] text-zinc-500">
          Your claim is now pending review. You can track its status in My Claims.
        </p>

        <div className="flex items-center gap-3">
          <Link
            href="/account"
            className="inline-flex items-center rounded border border-amber-800/60 bg-amber-950/30 px-3 py-1.5 text-[12px] font-medium text-amber-300 hover:bg-amber-950/50 transition-colors"
          >
            View my claims →
          </Link>
          <button
            onClick={onDone}
            className="text-[11px] text-zinc-600 hover:text-zinc-400 transition-colors"
          >
            Back to profile
          </button>
        </div>
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
              Steps:
            </p>
            <ol className="list-decimal list-inside space-y-1.5 text-[11px] text-zinc-500">
              <li>Enter your public profile URL below and submit.</li>
              <li>
                Copy the verification code shown on the next screen.
              </li>
              <li>
                Paste it anywhere in your{" "}
                <span className="text-zinc-400">{platformLabel}</span> so it is
                publicly visible.
              </li>
              <li>
                Our team will confirm the code is visible and approve your claim.
                You can remove the code after verification.
              </li>
            </ol>
          </div>
        ) : (
          <div className="space-y-1.5 rounded border border-zinc-800 bg-zinc-900/30 px-4 py-3">
            <p className="text-[11px] font-semibold text-zinc-300">
              Acceptable evidence:
            </p>
            <ul className="list-disc list-inside space-y-1 text-[11px] text-zinc-500">
              <li>A pinned post, video, or story linking this account to you</li>
              <li>A public announcement or bio mentioning your identity</li>
              <li>Your personal or business website that references this account</li>
            </ul>
            <p className="text-[11px] text-zinc-600 pt-1">
              Do not submit login credentials, private screenshots, or DMs.
              Evidence must be publicly viewable without an account.
            </p>
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
          <p className="text-[10px] text-zinc-600">
            Must be publicly accessible without logging in. Example:{" "}
            {method === "bio_code"
              ? "https://www.youtube.com/channel/UC..."
              : "https://yourdomain.com/about or a public post URL"}
          </p>
        </div>

        {/* Optional note */}
        <div className="space-y-1.5">
          <label className="block text-[11px] font-medium text-zinc-400">
            Note to reviewer{" "}
            <span className="text-zinc-600 font-normal">(optional)</span>
          </label>
          <textarea
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. 'The code is in the About section' or 'I linked this channel from my personal site'"
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
          displayName: p.title ?? p.creator_handle ?? creatorId,
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
              <div className="px-5 py-4 space-y-3">
                <HowToClaim platform={profile.platform} />
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

          {/* Wrong data footer */}
          <p className="text-[10px] text-zinc-700 px-1 pb-2">
            Spot incorrect data on this profile?{" "}
            <a
              href="mailto:support@fragranceindex.ai"
              className="hover:text-zinc-500 transition-colors"
            >
              support@fragranceindex.ai
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
