// Stytch B2B client + the two request headers the backend expects.
//
// Names verified against the installed packages (@stytch/react 20.3.0,
// @stytch/vanilla-js 6.3.0) — see docs/STYTCH_NOTES.md "Frontend":
//   createStytchB2BClient(publicToken)          @stytch/react/b2b
//   client.session.getTokens() -> { session_jwt, session_token } | null
//
// Resilience: if VITE_STYTCH_PUBLIC_TOKEN is unset the app boots WITHOUT auth
// (AUTH_CONFIGURED=false), no provider, no login screen — matching a backend
// with AUTH_ENABLED=false. Same ethos as the localStorage try/catch in the
// store: a missing/failed integration degrades, it never white-screens.

import { createStytchB2BClient } from "@stytch/react/b2b";
type StytchB2BClient = ReturnType<typeof createStytchB2BClient>;

export const STYTCH_PUBLIC_TOKEN: string = (import.meta.env.VITE_STYTCH_PUBLIC_TOKEN ?? "").trim();
export const AUTH_CONFIGURED = STYTCH_PUBLIC_TOKEN.length > 0;

let _client: StytchB2BClient | null = null;
let _clientFailed = false;

export function getStytchClient(): StytchB2BClient | null {
  if (!AUTH_CONFIGURED || _clientFailed) return null;
  if (_client) return _client;
  try {
    _client = createStytchB2BClient(STYTCH_PUBLIC_TOKEN);
  } catch (e) {
    // A malformed token or a blocked SDK bootstrap must not take the UI down.
    console.error("Stytch client failed to initialize; running without auth", e);
    _clientFailed = true;
    return null;
  }
  return _client;
}

// Headers for every API call (REST and SSE). Both are sent so the backend can
// verify the JWT locally on hot paths and the opaque token over the network on
// sensitive routes. Empty when unconfigured or logged out — the backend then
// answers 401 (flag on) or ignores them (flag off).
export function authHeaders(): Record<string, string> {
  const client = getStytchClient();
  if (!client) return {};
  try {
    const t = client.session.getTokens();
    if (!t || !t.session_jwt || !t.session_token) return {};
    return { Authorization: `Bearer ${t.session_jwt}`, "X-Session-Token": t.session_token };
  } catch {
    return {};
  }
}
