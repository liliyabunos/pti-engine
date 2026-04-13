import { ExternalLink, Lock } from "lucide-react";
import { EmptyState } from "@/components/primitives/EmptyState";
import { fmtPlatform, fmtCount, fmtDatetime } from "@/lib/formatters";
import type { RecentMentionRow } from "@/lib/api/types";

interface RecentMentionsProps {
  mentions: RecentMentionRow[];
}

function isPublicUrl(url: string | null | undefined): boolean {
  return typeof url === "string" && url.startsWith("http");
}

export function RecentMentions({ mentions }: RecentMentionsProps) {
  if (!mentions.length) {
    return <EmptyState compact message="No recent mentions" />;
  }

  return (
    <ul className="divide-y divide-zinc-800/50">
      {mentions.map((m, i) => (
        <li
          key={i}
          className="flex items-start gap-3 px-2 py-2.5 hover:bg-zinc-800/20"
        >
          {/* Platform pill */}
          <span className="mt-px w-14 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
            {fmtPlatform(m.source_platform)}
          </span>

          {/* Author + engagement */}
          <div className="min-w-0 flex-1">
            {m.author_name ? (
              <span className="block truncate text-xs text-zinc-300">
                {m.author_name}
              </span>
            ) : (
              <span className="block text-[10px] text-zinc-600">
                Unknown author
              </span>
            )}
            {m.engagement != null && (
              <span className="text-[10px] text-zinc-600">
                {fmtCount(m.engagement)}{" "}
                <span className="text-zinc-700">engagement</span>
              </span>
            )}
          </div>

          {/* Date + link */}
          <div className="shrink-0 text-right">
            <span className="block text-[10px] tabular-nums text-zinc-600">
              {fmtDatetime(m.occurred_at)}
            </span>
            {isPublicUrl(m.source_url) ? (
              <a
                href={m.source_url!}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-0.5 inline-flex items-center gap-0.5 text-[10px] text-zinc-500 hover:text-amber-400"
              >
                <ExternalLink size={10} />
                open
              </a>
            ) : (
              <span className="mt-0.5 inline-flex items-center gap-0.5 text-[10px] text-zinc-700">
                <Lock size={9} />
                internal
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
