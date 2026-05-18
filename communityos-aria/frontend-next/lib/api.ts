/**
 * ARIA backend client.
 *
 * Every call goes through `request()` which handles:
 *   - prefixing the base URL from NEXT_PUBLIC_ARIA_API_URL
 *   - injecting Bearer auth (auto-logging in if needed)
 *   - retrying once on a 401 (token expired → refresh → retry)
 *   - generating per-request `X-Request-ID` so server-side logs are traceable
 *
 * The single retry is intentional — we never want an infinite loop if the
 * backend genuinely refuses our identity.
 */
import type {
  AmenityListResponse,
  ChatRequest,
  ChatResponse,
  DemoIdentity,
  LoginRequest,
  LoginResponse,
} from './types';
import { DEMO_IDENTITY, ensureToken, refreshToken } from './auth';

export const API_BASE =
  process.env.NEXT_PUBLIC_ARIA_API_URL?.replace(/\/+$/, '') ||
  'http://localhost:8080';

function genRequestId(): string {
  // crypto.randomUUID exists in evergreen browsers + recent Node.
  const id =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return id.replace(/-/g, '').slice(0, 32);
}

interface RequestOpts {
  method?: 'GET' | 'POST';
  body?: unknown;
  auth?: boolean;       // include Bearer token (default: true)
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { method = 'GET', body, auth = true, signal } = opts;
  const url = `${API_BASE}${path}`;

  const headers: Record<string, string> = {
    'X-Request-ID': genRequestId(),
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) headers['Authorization'] = `Bearer ${await ensureToken()}`;

  const doFetch = async (token?: string) => {
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  };

  let resp = await doFetch();

  if (resp.status === 401 && auth) {
    const fresh = await refreshToken();
    resp = await doFetch(fresh);
  }

  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`ARIA ${method} ${path} → ${resp.status} ${text.slice(0, 240)}`);
  }
  return resp.json() as Promise<T>;
}

// ── Public API ─────────────────────────────────────────────────────────

export async function login(identity: DemoIdentity = DEMO_IDENTITY): Promise<LoginResponse> {
  const payload: LoginRequest = identity;
  return request<LoginResponse>('/aria/login', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

export async function chat(req: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/aria/chat', {
    method: 'POST',
    body: req,
  });
}

export async function listAmenities(orgId: string): Promise<AmenityListResponse> {
  // GET returns a bare list, wrap it consistently for the UI.
  const items = await request<unknown>(`/society/amenities?org_id=${encodeURIComponent(orgId)}`, {
    auth: false,
  });
  return { items: Array.isArray(items) ? items as AmenityListResponse['items'] : [] };
}

export async function healthOk(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/health`);
    return r.ok;
  } catch {
    return false;
  }
}
