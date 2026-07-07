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

// --- Machines + FOCAS mirror reads (docs/04 §Machines, §Offsets-read). -------

export interface FocasState {
  connected: boolean;
  last_polled_at: string | null;
  lag_seconds: number | null;
}

export interface Machine {
  id: string;
  name: string;
  serial_number: string | null;
  control_model: string;
  ip_address: string;
  focas_port: number;
  pot_count: number;
  probe_pot: number | null;
  probe_t_number: number | null;
  probe_h_register: number | null;
  offset_register_count: number;
  atc_strategy: string;
  has_tsc: boolean;
  has_toolsetter: boolean;
  poll_interval_seconds: number;
  enabled: boolean;
  retired_at: string | null;
  focas_state: FocasState;
}

export interface OffsetRegister {
  register_number: number;
  register_type: string;
  value_mm: string;
  last_polled_at: string;
  last_changed_at: string;
}

export interface Pot {
  pot_number: number;
  t_number: number | null;
  last_polled_at: string;
  last_changed_at: string;
}

export interface ToolLife {
  t_number: number;
  life_count: number | null;
  life_max: number | null;
  status: string | null;
  last_polled_at: string;
}

// --- Audit (docs/04 §Audit; enveloped, admin-or-own-scoped). -----------------

export interface AuditEntry {
  id: number;
  occurred_at: string;
  user_id: string | null;
  machine_id: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string;
  before_value: Record<string, unknown> | null;
  after_value: Record<string, unknown> | null;
  reason: string | null;
  success: boolean;
  error: string | null;
}
