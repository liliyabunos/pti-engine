"use client";

import { useState } from "react";
import { X, Plus, Check } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWatchlists, addWatchlistItem, createWatchlist } from "@/lib/api/watchlists";

interface AddToWatchlistModalProps {
  entityId: string;
  entityType: string;
  canonicalName: string;
  onClose: () => void;
}

export function AddToWatchlistModal({
  entityId,
  entityType,
  canonicalName,
  onClose,
}: AddToWatchlistModalProps) {
  const [creatingNew, setCreatingNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [successId, setSuccessId] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: fetchWatchlists,
    staleTime: 10_000,
  });

  const addMutation = useMutation({
    mutationFn: (watchlistId: string) =>
      addWatchlistItem(watchlistId, entityId, entityType),
    onSuccess: (_, watchlistId) => {
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      qc.invalidateQueries({ queryKey: ["watchlist", watchlistId] });
      setSuccessId(watchlistId);
    },
  });

  const createAndAddMutation = useMutation({
    mutationFn: async () => {
      const wl = await createWatchlist(newName.trim());
      return addWatchlistItem(wl.id, entityId, entityType);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      setCreatingNew(false);
      setNewName("");
    },
  });

  const watchlists = data?.watchlists ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-sm rounded border border-zinc-700 bg-zinc-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <span className="text-sm font-medium text-zinc-200">Add to Watchlist</span>
            <p className="text-[10px] text-zinc-500">{canonicalName}</p>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X size={14} />
          </button>
        </div>

        <div className="p-4">
          {isLoading ? (
            <p className="text-[11px] text-zinc-600">Loading watchlists…</p>
          ) : watchlists.length === 0 ? (
            <p className="mb-3 text-[11px] text-zinc-500">
              No watchlists yet. Create one below.
            </p>
          ) : (
            <ul className="mb-3 max-h-48 space-y-1 overflow-y-auto">
              {watchlists.map((wl) => (
                <li key={wl.id}>
                  <button
                    onClick={() => addMutation.mutate(wl.id)}
                    disabled={addMutation.isPending}
                    className="flex w-full items-center justify-between rounded border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-left text-[12px] text-zinc-300 hover:border-zinc-600 hover:bg-zinc-800/50 disabled:opacity-40"
                  >
                    <span className="truncate">{wl.name}</span>
                    <span className="ml-2 flex shrink-0 items-center gap-1 text-[10px] text-zinc-600">
                      {successId === wl.id ? (
                        <Check size={11} className="text-emerald-400" />
                      ) : (
                        wl.item_count
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {addMutation.isError && (
            <p className="mb-2 text-[11px] text-red-400">
              {String((addMutation.error as Error)?.message ?? "Error")}
            </p>
          )}

          {/* Create new list inline */}
          {creatingNew ? (
            <div className="space-y-2">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New watchlist name"
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => createAndAddMutation.mutate()}
                  disabled={!newName.trim() || createAndAddMutation.isPending}
                  className="flex-1 rounded border border-zinc-600 bg-zinc-800 py-1.5 text-[11px] text-zinc-200 hover:bg-zinc-700 disabled:opacity-40"
                >
                  {createAndAddMutation.isPending ? "Creating…" : "Create & Add"}
                </button>
                <button
                  onClick={() => setCreatingNew(false)}
                  className="px-3 text-[11px] text-zinc-500 hover:text-zinc-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setCreatingNew(true)}
              className="flex w-full items-center justify-center gap-1 rounded border border-dashed border-zinc-700 py-2 text-[11px] text-zinc-500 hover:border-zinc-500 hover:text-zinc-300"
            >
              <Plus size={10} />
              New watchlist
            </button>
          )}
        </div>

        <div className="flex justify-end border-t border-zinc-800 px-4 py-2">
          <button
            onClick={onClose}
            className="text-[11px] text-zinc-400 hover:text-zinc-200"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
