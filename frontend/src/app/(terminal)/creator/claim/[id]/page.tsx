"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

/**
 * C1 — Creator Profile Claim stub.
 *
 * Auth-required (protected by middleware — not in PUBLIC_PATHS).
 * This page is a placeholder for the claim flow.
 * Full verification form arrives in a future phase.
 */

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CreatorClaimPage({ params }: PageProps) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const router = useRouter();

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Claim Creator Profile"
        subtitle={`Profile ID: ${decoded}`}
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
        <TerminalPanel>
          <div className="space-y-4 px-5 py-6">
            <h2 className="text-sm font-semibold text-zinc-200">
              Creator verification is coming soon
            </h2>
            <p className="text-[12px] leading-relaxed text-zinc-500">
              We&apos;re building a verification flow so creators can claim their
              profiles, unlock additional analytics, and receive attribution credit.
            </p>
            <p className="text-[12px] leading-relaxed text-zinc-500">
              If you believe this profile belongs to you and would like to be
              notified when the claim feature launches, please contact us at{" "}
              <a
                href="mailto:support@fragranceindex.ai"
                className="text-amber-400 hover:underline"
              >
                support@fragranceindex.ai
              </a>
              .
            </p>
            <button
              onClick={() => router.back()}
              className="mt-2 inline-flex items-center gap-1.5 rounded border border-zinc-700/60 bg-zinc-800/40 px-3 py-1.5 text-[12px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
            >
              <ArrowLeft size={11} />
              Return to profile
            </button>
          </div>
        </TerminalPanel>
      </div>
    </div>
  );
}
