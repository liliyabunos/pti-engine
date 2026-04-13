"use client";

import { clsx } from "clsx";
import { Search, X, Loader2 } from "lucide-react";

// ---------------------------------------------------------------------------
// SearchInput
//
// Terminal-style text input with:
//   - magnifier icon on the left
//   - optional loading spinner (replaces magnifier when loading=true)
//   - clear (×) button appears when value is non-empty
// ---------------------------------------------------------------------------

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onClear?: () => void;
  placeholder?: string;
  loading?: boolean;
  className?: string;
}

export function SearchInput({
  value,
  onChange,
  onClear,
  placeholder = "Search…",
  loading = false,
  className,
}: SearchInputProps) {
  const hasValue = value.length > 0;

  const handleClear = () => {
    onChange("");
    onClear?.();
  };

  return (
    <div className={clsx("relative flex items-center", className)}>
      {/* Left icon: spinner when loading, magnifier otherwise */}
      <span className="pointer-events-none absolute left-2.5 flex items-center text-zinc-500">
        {loading ? (
          <Loader2 size={13} className="animate-spin" />
        ) : (
          <Search size={13} strokeWidth={2} />
        )}
      </span>

      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={clsx(
          "h-7 w-full rounded border border-zinc-700 bg-zinc-900",
          "py-1 pl-8 pr-7 text-xs text-zinc-200",
          "placeholder:text-zinc-600",
          "outline-none",
          "transition-colors",
          "focus:border-zinc-500",
          // No ring — terminal style
        )}
      />

      {/* Clear button — shown only when there is input */}
      {hasValue && (
        <button
          type="button"
          onClick={handleClear}
          aria-label="Clear search"
          className="absolute right-2 flex items-center text-zinc-600 hover:text-zinc-300"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}
