import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// SectionHeader
//
// Used at the top of every panel section.
// Title is always uppercase + wide tracking — terminal style.
// Subtitle is a secondary dim line below the title.
// Actions slot is right-aligned (buttons, toggles, refresh).
// ---------------------------------------------------------------------------

interface SectionHeaderProps {
  title: string;
  /** Short secondary label, e.g. "20 entities" or "last 7d" */
  subtitle?: string;
  /** Right-aligned controls */
  actions?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  title,
  subtitle,
  actions,
  className,
}: SectionHeaderProps) {
  return (
    <div className={clsx("flex min-w-0 items-center justify-between gap-4", className)}>
      {/* Left: title + optional subtitle */}
      <div className="min-w-0">
        <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
          {title}
        </h3>
        {subtitle && (
          <p className="mt-px text-[10px] text-zinc-700">{subtitle}</p>
        )}
      </div>

      {/* Right: action slot */}
      {actions && (
        <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
      )}
    </div>
  );
}
