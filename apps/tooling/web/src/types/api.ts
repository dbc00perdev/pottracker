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
