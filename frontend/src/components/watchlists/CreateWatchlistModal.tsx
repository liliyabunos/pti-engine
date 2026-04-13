"use client";

import { useRef, useState } from "react";
import { X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createWatchlist } from "@/lib/api/watchlists";

interface CreateWatchlistModalProps {
  onClose: () => void;
  onCreated: (id: string) => void;
}

export function CreateWatchlistModal({ onClose, onCreated }: CreateWatchlistModalProps) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const mutation = useMutation({
    mutationFn: () => createWatchlist(name.trim(), desc.trim() || undefined),
    onSuccess: (wl) => {
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      onCreated(wl.id);
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    mutation.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-sm rounded border border-zinc-700 bg-zinc-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <span className="text-sm font-medium text-zinc-200">New Watchlist</span>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X size={14} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={submit} className="space-y-3 p-4">
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Name *</label>
            <input
              ref={inputRef}
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Breakout Watchlist"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Description (optional)</label>
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Brief description"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
            />
          </div>

          {mutation.isError && (
            <p className="text-[11px] text-red-400">
              {String((mutation.error as Error)?.message ?? "Error creating watchlist")}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-[11px] text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || mutation.isPending}
              className="rounded border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-200 hover:border-zinc-500 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {mutation.isPending ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
