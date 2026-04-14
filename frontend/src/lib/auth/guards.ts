/**
 * Authorization guards — answers "is this authenticated user approved to use PTI?"
 *
 * Authentication (who are you?) is handled by Supabase.
 * Authorization (are you approved?) is handled by the app_users table in our DB.
 *
 * These functions query the PTI backend API, which reads app_users from
 * the production PostgreSQL database.
 *
 * Rules:
 *   - A valid Supabase session alone does NOT grant terminal access.
 *   - The user's email must exist in app_users with access_status = 'approved'.
 *   - Revoked users are blocked at the callback route and at every middleware check.
 *
 * Failure modes:
 *   - API unreachable → fail closed (return null / false) — no silent open access
 *   - API timeout (>3s) → same: fail closed
 *   - Missing env var → logs a startup error, fails closed
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

/** Warn loudly at module load time if the API base URL is missing. */
if (!API_BASE) {
  if (typeof window !== "undefined") {
    console.error(
      "[PTI] NEXT_PUBLIC_API_BASE_URL is not set. " +
        "All auth guard checks will fail closed — no one can log in. " +
        "Set this environment variable to your PTI API URL."
    );
  }
}

const AUTH_TIMEOUT_MS = 3_000;

/** Fetch with a hard timeout. Throws on timeout. */
async function fetchWithTimeout(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export interface AppUser {
  email: string;
  role: "viewer" | "admin";
  access_status: "pending" | "approved" | "revoked";
}

/**
 * Check whether an email is approved in app_users.
 *
 * Called from:
 *   1. /login — before sending the magic link (don't send to unapproved emails)
 *   2. /auth/callback — after Supabase confirms identity, before granting session
 *   3. middleware — on every protected request
 *
 * Returns null if the email is not found, env is misconfigured, API is
 * unreachable, or the request times out. Always fail closed.
 */
export async function getAppUser(email: string): Promise<AppUser | null> {
  if (!API_BASE) return null;
  try {
    const res = await fetchWithTimeout(
      `${API_BASE}/api/v1/auth/users/${encodeURIComponent(email.toLowerCase())}`,
      { cache: "no-store" }
    );
    if (!res.ok) return null;
    return (await res.json()) as AppUser;
  } catch (err) {
    // AbortError = timeout; TypeError = network failure — both fail closed
    if ((err as Error).name !== "AbortError") {
      console.error("[PTI] getAppUser fetch failed:", (err as Error).message);
    }
    return null;
  }
}

/** Return true only when the user exists AND is approved. */
export async function isApprovedUser(email: string): Promise<boolean> {
  const user = await getAppUser(email);
  return user?.access_status === "approved";
}

