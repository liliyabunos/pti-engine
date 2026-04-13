import { clsx } from "clsx";

interface HeaderProps {
  /** Page title shown in bold */
  title: string;
  /** Dimmed secondary label, e.g. date or count */
  subtitle?: string;
  /** Right-side action buttons / controls */
  actions?: React.ReactNode;
  /** Extra class for the outer element */
  className?: string;
}

/**
 * Per-page top header bar.
 *
 * Sits flush at the top of the main content region, below the global
 * StatusBar. Always 40px tall so layout doesn't shift between pages.
 */
export function Header({ title, subtitle, actions, className }: HeaderProps) {
  return (
    <header
      className={clsx(
        "flex h-10 shrink-0 items-center justify-between",
        "border-b border-zinc-800 bg-zinc-950",
        "px-5",
        className,
      )}
    >
      {/* Left: title + subtitle */}
      <div className="flex min-w-0 items-baseline gap-2.5">
        <h1 className="truncate text-sm font-semibold text-zinc-100">
          {title}
        </h1>
        {subtitle && (
          <span className="hidden shrink-0 text-[11px] text-zinc-600 sm:block">
            {subtitle}
          </span>
        )}
      </div>

      {/* Right: action slot */}
      {actions && (
        <div className="ml-4 flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
