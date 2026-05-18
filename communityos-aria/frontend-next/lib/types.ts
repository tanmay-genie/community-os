/**
 * TypeScript types mirroring ARIA's REST contract.
 *
 * Every shape here is what the ARIA backend (FastAPI) actually serialises.
 * Keep these in sync with `communityos-aria/chat_api.py` and
 * `communityos-aria/aria/society/routes.py`.
 */

// ── Auth ────────────────────────────────────────────────────────────────

export interface LoginRequest {
  twin_id: string;
  api_key: string;
  org_id: string;
}

export interface LoginResponse {
  access_token: string;
  expires_in: number;
  twin_id: string;
  role: 'member' | 'admin';
  org_id: string;
}

// ── Chat ────────────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  role?: 'member' | 'admin';
}

export interface ChatResponse {
  reply: string;
  conversation_id: string;
  action_taken: string;
  confidence?: number;
  /** Structured signals — useful for debugging the LLM path. */
  signals?: Record<string, unknown>;
  /** Suggested follow-up actions ARIA recommends. */
  suggestions?: Array<{ intent: string; display: string }>;
}

// ── Society — Amenities ─────────────────────────────────────────────────

export interface Amenity {
  amenity_id: string;
  name: string;
  display_name: string;
  type: string;            // gym | pool | court_badminton | ... | other
  description: string;
  features: string[];
  block: string;
  floor: string;
  location: string;
  capacity_per_slot: number;
  slot_duration_mins: number;
  open_time: string;       // 'HH:MM'
  close_time: string;      // 'HH:MM'
  image_url?: string;
}

export interface AmenityListResponse {
  type?: string;
  count?: number;
  items: Amenity[];
}

// ── Structured prefixes (chat reply renders rich cards) ────────────────

export interface AmenitiesPayload {
  type?: string;          // present when filtered by type
  items: Amenity[];
}

export interface BookingPayload {
  booking_id: string;
  amenity_id?: string;
  amenity: string;
  location?: string;
  date: string;
  slot?: string;
  remaining_capacity?: number;
}

export interface BylawSection {
  section: string;        // e.g. "3.1"
  title: string;          // e.g. "Hardwood Flooring"
  text: string;
  citation: string;       // e.g. "§3.1 Hardwood Flooring"
}

export interface BylawPayload {
  question: string;
  results: BylawSection[];
}

/** Discriminated union for parsed structured replies. */
export type StructuredReply =
  | { kind: 'amenities'; data: AmenitiesPayload; caption: string }
  | { kind: 'booking';   data: BookingPayload;   caption: string }
  | { kind: 'bylaw';     data: BylawPayload;     caption: string }
  | { kind: 'text';      data: null;             caption: string };
