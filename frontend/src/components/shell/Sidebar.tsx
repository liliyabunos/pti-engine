"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  LayoutDashboard,
  SlidersHorizontal,
  Users,
  BookMarked,
  BellRing,
  PlusCircle,
  type LucideIcon,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Nav definition
// ---------------------------------------------------------------------------

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  placeholder?: boolean; // grayed out + "soon" pill
}

const PRIMARY_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/screener", label: "Screener", icon: SlidersHorizontal },
  { href: "/creators", label: "Creators", icon: Users },
];

const SECONDARY_NAV: NavItem[] = [
  { href: "/watchlists", label: "Watchlists", icon: BookMarked, placeholder: true },
  { href: "/alerts", label: "Alerts", icon: BellRing, placeholder: true },
  { href: "/submit-source", label: "Suggest Source", icon: PlusCircle },
];

// ---------------------------------------------------------------------------
// Single nav link
// ---------------------------------------------------------------------------

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const { href, label, icon: Icon, placeholder } = item;

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={clsx(
        // base
        "group relative flex h-8 items-center gap-2.5 rounded-sm px-2 text-xs font-medium transition-colors",
        // active
        active && "bg-zinc-800 text-zinc-100",
        // idle & placeholder
        !active && placeholder && "text-zinc-600 hover:text-zinc-500",
        // idle & normal
        !active && !placeholder && "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200",
      )}
    >
      {/* Active left-edge accent */}
      {active && (
        <span className="absolute left-0 top-1 h-6 w-0.5 rounded-full bg-amber-400" />
      )}

      <Icon
        size={14}
        strokeWidth={active ? 2 : 1.75}
        className={clsx(
          "shrink-0 transition-colors",
          active ? "text-amber-400" : placeholder ? "text-zinc-700" : "text-zinc-500 group-hover:text-zinc-300",
        )}
      />

      {/* Label — hidden on icon-only width, visible on expanded */}
      <span className="hidden flex-1 lg:block">{label}</span>

      {/* "soon" pill for placeholders */}
      {placeholder && (
        <span className="ml-auto hidden rounded-sm bg-zinc-900 px-1 py-px text-[9px] font-semibold uppercase tracking-wider text-zinc-700 lg:inline">
          soon
        </span>
      )}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

export function Sidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <aside
      className={clsx(
        "flex h-full shrink-0 flex-col",
        "border-r border-zinc-800 bg-zinc-950",
        // icon-only on small screens, expanded on lg+
        "w-[52px] lg:w-[192px]",
      )}
    >
      {/* ── Logo ─────────────────────────────────────────── */}
      <div className="flex h-10 shrink-0 items-center border-b border-zinc-800 px-3 lg:px-3.5">
        {/* Monogram */}
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm bg-amber-400">
          <span className="text-[9px] font-black leading-none tracking-tight text-zinc-950">
            PT
          </span>
        </div>
        {/* Wordmark */}
        <div className="ml-2.5 hidden leading-none lg:block">
          <p className="text-[11px] font-bold tracking-tight text-zinc-100">
            PTI Terminal
          </p>
          <p className="text-[9px] tracking-widest text-zinc-600">
            MARKET ENGINE
          </p>
        </div>
      </div>

      {/* ── Primary navigation ───────────────────────────── */}
      <nav className="flex flex-1 flex-col gap-px overflow-y-auto p-2" aria-label="Primary">
        {/* Primary group */}
        <div className="space-y-px">
          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </div>

        {/* Divider */}
        <div className="my-2 border-t border-zinc-800/70" />

        {/* Secondary group */}
        <div className="space-y-px">
          {SECONDARY_NAV.map((item) => (
            <NavLink key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </div>
      </nav>

      {/* ── Footer ───────────────────────────────────────── */}
      <div className="shrink-0 border-t border-zinc-800 px-3 py-2.5">
        {/* Expanded label */}
        <p className="hidden text-[9px] uppercase tracking-[0.15em] text-zinc-700 lg:block">
          Perfume Trend Intelligence
        </p>
        {/* Collapsed dot */}
        <div className="h-1 w-1 rounded-full bg-zinc-800 lg:hidden" />
      </div>
    </aside>
  );
}
