/**
 * Auto-login + token management.
 *
 * For the demo we hardcode a known twin via NEXT_PUBLIC_DEMO_* env vars and
 * exchange those for a JWT against `/aria/login` on first call. In a real
 * deployment this is replaced by an actual auth flow (e.g. building-issued
 * one-time codes, owner email + SMS verification, SSO).
 *
 * The JWT is cached in `localStorage` and refreshed automatically on 401.
 */
import { login } from './api';

const KEY_TOKEN = 'aria-token';
const KEY_TOKEN_EXP = 'aria-token-exp';

export interface DemoIdentity {
  twin_id: string;
  api_key: string;
  org_id: string;
}

export const DEMO_IDENTITY: DemoIdentity = {
  twin_id: process.env.NEXT_PUBLIC_DEMO_TWIN_ID || 'tanmay_resident',
  api_key: process.env.NEXT_PUBLIC_DEMO_API_KEY || 'tanmay-key-001',
  org_id:  process.env.NEXT_PUBLIC_DEMO_ORG_ID  || 'maple_heights',
};

function readToken(): { token: string; exp: number } | null {
  if (typeof window === 'undefined') return null;
  const token = window.localStorage.getItem(KEY_TOKEN) || '';
  const exp = Number(window.localStorage.getItem(KEY_TOKEN_EXP) || 0);
  return token ? { token, exp } : null;
}

function writeToken(token: string, expSecondsFromNow: number) {
  if (typeof window === 'undefined') return;
  const exp = Math.floor(Date.now() / 1000) + expSecondsFromNow;
  window.localStorage.setItem(KEY_TOKEN, token);
  window.localStorage.setItem(KEY_TOKEN_EXP, String(exp));
}

export function clearToken() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(KEY_TOKEN);
  window.localStorage.removeItem(KEY_TOKEN_EXP);
}

function isValid(t: { token: string; exp: number } | null): t is { token: string; exp: number } {
  // Refresh 30s before actual expiry to avoid races.
  return !!t && t.token.length > 0 && t.exp > Math.floor(Date.now() / 1000) + 30;
}

/**
 * Returns a valid Bearer token, calling /aria/login transparently if the
 * cached token is missing or expired.
 */
export async function ensureToken(): Promise<string> {
  const cached = readToken();
  if (isValid(cached)) return cached.token;

  const resp = await login(DEMO_IDENTITY);
  writeToken(resp.access_token, resp.expires_in || 86400);
  return resp.access_token;
}

/**
 * After a 401 from the API, drop the cached token and force a re-login on
 * the next request.
 */
export async function refreshToken(): Promise<string> {
  clearToken();
  return ensureToken();
}
