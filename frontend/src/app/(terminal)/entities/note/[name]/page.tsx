"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";

import { fetchNoteDetail } from "@/lib/api/notes";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { ErrorState } from "@/components/primitives/ErrorState";
import { TableSkeleton } from "@/components/primitives/LoadingSkeleton";

export default function NoteDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);
  const noteName = decodeURIComponent(name);
  const router = useRouter();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["note-detail", noteName],
    queryFn: () => fetchNoteDetail(noteName),
    staleTime: 10 * 60_000,
  });

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title={noteName}
        subtitle={
          data ? `${data.perfume_count.toLocaleString()} perfumes` : "Note"
        }
        actions={
          <button
            onClick={() => router.push("/screener?mode=notes")}
            className="flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
          >
            <ArrowLeft size={11} />
            All Notes
          </button>
        }
      />

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {isError && (
          <ErrorState message={String(error)} />
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
          {/* Perfumes using this note */}
          <TerminalPanel noPad>
            <div className="p-4 pb-3">
              <SectionHeader
                title="Top Entities with this Note"
                subtitle={data ? `${data.top_perfumes.length} shown` : undefined}
              />
            </div>
            {isLoading ? (
              <TableSkeleton rows={15} cols={4} />
            ) : (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Brand</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.top_perfumes ?? []).map((p) => {
                    const dest = p.entity_id
                      ? `/entities/${p.entity_type === "brand" ? "brand" : "perfume"}/${p.entity_id}`
                      : p.resolver_id != null
                      ? `/entities/perfume/${p.resolver_id}`
                      : null;
                    return (
                    <tr
                      key={p.canonical_name}
                      onClick={dest ? () => router.push(dest) : undefined}
                      className={clsx(
                        "border-b border-zinc-900 transition-colors",
                        dest ? "cursor-pointer hover:bg-zinc-900" : "opacity-40",
                      )}
                    >
                      <td className="px-4 py-2">
                        {p.entity_type === "brand" ? (
                          <span className="rounded border border-sky-800 bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-400">
                            BRAND
                          </span>
                        ) : (
                          <span className="rounded border border-violet-800 bg-violet-950 px-1.5 py-0.5 text-[10px] text-violet-400">
                            PERFUME
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-zinc-200">
                        {p.canonical_name}
                      </td>
                      <td className="px-4 py-2 text-zinc-500">
                        {p.brand_name ?? "—"}
                      </td>
                      <td className="px-4 py-2">
                        {p.entity_id ? (
                          <span className="rounded border border-emerald-800 bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-400">
                            Tracked
                          </span>
                        ) : (
                          <span className="rounded border border-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-600">
                            In Catalog
                          </span>
                        )}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </TerminalPanel>

          {/* Related accords */}
          <TerminalPanel noPad>
            <div className="p-4 pb-3">
              <SectionHeader
                title="Related Accords"
                subtitle="co-occur most with this note"
              />
            </div>
            {isLoading ? (
              <TableSkeleton rows={10} cols={2} />
            ) : (
              <div className="flex flex-wrap gap-1.5 px-4 pb-4">
                {(data?.related_accords ?? []).map((a) => (
                  <button
                    key={a.accord_name}
                    onClick={() =>
                      router.push(
                        `/entities/accord/${encodeURIComponent(a.accord_name)}`,
                      )
                    }
                    className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[11px] text-violet-300 transition-colors hover:border-violet-700 hover:text-violet-100"
                  >
                    {a.accord_name}
                    <span className="text-zinc-600">{a.co_count}</span>
                  </button>
                ))}
                {!isLoading && !data?.related_accords.length && (
                  <span className="text-[12px] text-zinc-600">
                    No accord data available
                  </span>
                )}
              </div>
            )}
          </TerminalPanel>
        </div>
      </div>
    </div>
  );
}
