/** Typed fetch wrapper. Auth rides on the httpOnly cookie set at login. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// ── API types (mirror cartograph schemas) ────────────────────────────────────

export interface Point {
  lng: number;
  lat: number;
}

export interface User {
  id: string;
  tenant_id: string;
  email: string;
}

export interface ServiceArea {
  id: string;
  name: string;
  geometry: GeoJSON.MultiPolygon;
  rules: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type OrderState =
  | "created"
  | "assigned"
  | "picked_up"
  | "delivered"
  | "failed"
  | "cancelled";

export interface Order {
  id: string;
  pickup: Point;
  delivery: Point;
  pickup_address: string;
  delivery_address: string;
  promised_at: string;
  state: OrderState;
  driver_id: string | null;
  eta_seconds: number | null;
  geofence_meters: number;
  created_at: string;
}

export type DriverState = "offline" | "idle" | "en_route";

export interface Driver {
  id: string;
  name: string;
  phone: string;
  vehicle_type: "bike" | "scooter" | "car" | "van";
  state: DriverState;
  current_location: Point | null;
  current_location_updated_at: string | null;
  created_at: string;
}

export interface OptimizedStop {
  order_id: string;
  kind: "pickup" | "delivery";
  lng: number;
  lat: number;
  arrival_offset_s: number;
  cumulative_distance_m: number;
}

export interface OptimizeResult {
  route_id: string;
  stops: OptimizedStop[];
  total_duration_s: number;
  total_distance_m: number;
}

export interface CoverageCell {
  hex: string;
  count: number;
}

export interface Coverage {
  resolution: number;
  kind: "pickup" | "delivery";
  total_orders: number;
  cells: CoverageCell[];
}

export interface GeofenceEvent {
  id: string;
  driver_id: string;
  order_id: string | null;
  kind: "entered" | "exited" | "dwell_threshold";
  location: Point;
  occurred_at: string;
}
