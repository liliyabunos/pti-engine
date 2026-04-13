import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// TerminalPanel
//
// The foundational card/panel primitive. Every content block in the terminal
// sits inside one of these.
//
// Variants:
//   default — bordered, bg-zinc-900 (standard panel on zinc-950 page bg)
//   ghost   — no border, no bg  (transparent container, used inside panels)
//   inset   — darker bg, inner border (nested sub-section)
//
// Padding:
//   noPad   — disable default p-4 when the panel manages its own padding
//             regions (e.g. tables where the thead needs edge-to-edge)
// ---------------------------------------------------------------------------

type PanelVariant = "default" | "ghost" | "inset";

interface TerminalPanelProps {
  children: React.ReactNode;
  variant?: PanelVariant;
  /** Disable the default p-4 padding */
  noPad?: boolean;
  className?: string;
}

const variantStyles: Record<PanelVariant, string> = {
  default: "rounded border border-zinc-800 bg-zinc-900",
  ghost:   "rounded",
  inset:   "rounded border border-zinc-800/60 bg-zinc-950",
};

export function TerminalPanel({
  children,
  variant = "default",
  noPad = false,
  className,
}: TerminalPanelProps) {
  return (
    <div
      className={clsx(
        variantStyles[variant],
        !noPad && "p-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PanelDivider — a horizontal rule between sections inside a TerminalPanel
// ---------------------------------------------------------------------------

export function PanelDivider({ className }: { className?: string }) {
  return <div className={clsx("border-t border-zinc-800", className)} />;
}
