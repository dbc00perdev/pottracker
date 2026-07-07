// Hand-written types mirroring docs/04-api.md responses. No codegen in v1;
// revisit if drift becomes a problem.

export type Role = "viewer" | "operator" | "setter" | "admin";

export const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  operator: 1,
  setter: 2,
  admin: 3,
};

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface MeResponse {
  id: string;
  username: string;
  display_name: string;
  role: Role;
}

/** RFC 7807 problem+json body the API returns on errors. */
export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  [key: string]: unknown;
}

/** Envelope shared by every list endpoint (docs/04 §Conventions). */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- Tools (docs/04 §Tools). Decimal fields arrive as JSON strings. ----------

export interface ToolTypeRef {
  code: string;
  display_name: string;
}

export interface ToolAssignmentRef {
  machine_id: string;
  machine_name: string;
  t_number: number;
  h_register: number;
  d_register: number | null;
}

export interface Tool {
  id: string;
  short_id: string;
  tool_type: ToolTypeRef;
  diameter_mm: string;
  diameter_inch: string | null;
  flute_count: number | null;
  corner_radius_mm: string | null;
  flute_length_mm: string | null;
  overall_length_mm: string | null;
  shank_diameter_mm: string | null;
  substrate: string | null;
  coating: string | null;
  vendor: string | null;
  vendor_part_number: string | null;
  vendor_url: string | null;
  max_doc_mm: string | null;
  max_woc_mm: string | null;
  requires_tsc: boolean;
  requires_climb: boolean;
  is_consumable_class: boolean;
  regrind_count: number;
  notes: string | null;
  assignments: ToolAssignmentRef[];
  retired_at: string | null;
}

// --- Health (docs/04 §Health; public endpoint). -----------------------------

export interface HealthMachine {
  id: string;
  name: string;
  focas_connected: boolean;
  last_polled_at: string | null;
  lag_seconds: number | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  machines: HealthMachine[];
}
