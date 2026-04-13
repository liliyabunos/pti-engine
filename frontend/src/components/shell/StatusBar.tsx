"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity } from "lucide-react";
import { createClient } from "@/lib/auth/client";

function Clock() {
  const [time, setTime] = useState("");

  useEffect(() => {
    const fmt = () =>
      new Date().toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    setTime(fmt());
    const id = setInterval(() => setTime(fmt()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="tabular-nums text-zinc-500">{time}</span>
  );
}

function ApiDot() {
  const apiBase =
    typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
      : "";

  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    if (!apiBase) return;
    const check = () =>
      fetch(`${apiBase}/healthz`, { cache: "no-store" })
        .then((r) => setStatus(r.ok ? "ok" : "down"))
        .catch(() => setStatus("down"));

    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, [apiBase]);

  const dot =
    status === "ok"
      ? "bg-emerald-500"
      : status === "down"
        ? "bg-red-500"
        : "bg-zinc-600";

  const label =
    status === "ok" ? "API live" : status === "down" ? "API down" : "…";

  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      <span className="text-zinc-600">{label}</span>
    </span>
  );
}

function LogoutButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleLogout() {
    setLoading(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/");
  }

  return (
    <button
      onClick={handleLogout}
      disabled={loading}
      className="text-zinc-600 hover:text-zinc-400 transition-colors disabled:opacity-50"
    >
      {loading ? "…" : "logout"}
    </button>
  );
}

export function StatusBar() {
  return (
    <div className="flex h-7 shrink-0 items-center justify-between border-b border-zinc-800/60 bg-zinc-950 px-4 text-[10px] font-mono tracking-wide">
      {/* Left: brand */}
      <div className="flex items-center gap-2">
        <Activity size={11} className="text-amber-400" />
        <span className="font-semibold text-zinc-400">
          PTI MARKET TERMINAL
        </span>
        <span className="text-zinc-700">·</span>
        <span className="text-zinc-700">v1</span>
      </div>

      {/* Right: status + clock + logout */}
      <div className="flex items-center gap-3">
        <ApiDot />
        <span className="text-zinc-700">·</span>
        <Clock />
        <span className="text-zinc-700">·</span>
        <LogoutButton />
      </div>
    </div>
  );
}
