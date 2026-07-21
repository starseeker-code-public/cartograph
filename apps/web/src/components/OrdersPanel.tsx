import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Driver, GeofenceEvent, Order, OrderState, RouteGeometry } from "../lib/api";
import { api } from "../lib/api";
import { formatDistance, formatDuration, formatTime } from "../lib/format";

const NEXT_STATES: Partial<Record<OrderState, OrderState[]>> = {
  created: ["cancelled"],
  assigned: ["picked_up", "cancelled"],
  picked_up: ["delivered", "failed"],
};

const STATE_COLORS: Record<OrderState, string> = {
  created: "bg-slate-500",
  assigned: "bg-sky-600",
  picked_up: "bg-amber-600",
  delivered: "bg-green-600",
  failed: "bg-red-600",
  cancelled: "bg-slate-700",
};

interface Props {
  orders: Order[];
  drivers: Driver[];
  selectedOrderId: string | null;
  onSelect: (orderId: string | null) => void;
  onShowRoute: (line: RouteGeometry | null) => void;
}

export function OrdersPanel({ orders, drivers, selectedOrderId, onSelect, onShowRoute }: Props) {
  const selected = orders.find((o) => o.id === selectedOrderId) ?? null;
  return selected ? (
    <OrderDetail
      key={selected.id} // remount on order switch: mutation state must not leak
      order={selected}
      drivers={drivers}
      onBack={() => {
        onSelect(null);
        onShowRoute(null);
      }}
      onShowRoute={onShowRoute}
    />
  ) : (
    <ul className="space-y-2">
      {orders.length === 0 && <p className="text-sm text-slate-400">No orders yet.</p>}
      {orders.map((order) => (
        <li key={order.id}>
          <button
            onClick={() => onSelect(order.id)}
            className="w-full rounded-lg bg-slate-800 p-3 text-left hover:bg-slate-700"
          >
            <div className="flex items-center justify-between">
              <span className="truncate text-sm text-white">{order.delivery_address}</span>
              <span
                className={`ml-2 shrink-0 rounded px-2 py-0.5 text-xs text-white ${STATE_COLORS[order.state]}`}
              >
                {order.state}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-400">
              ETA {formatDuration(order.eta_seconds)} · promised {formatTime(order.promised_at)}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function OrderDetail({
  order,
  drivers,
  onBack,
  onShowRoute,
}: {
  order: Order;
  drivers: Driver[];
  onBack: () => void;
  onShowRoute: (line: RouteGeometry | null) => void;
}) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["orders"] });

  const events = useQuery({
    queryKey: ["geofence-events", order.id],
    queryFn: () =>
      api.get<GeofenceEvent[]>(`/api/geofence-events?order_id=${order.id}&limit=10`),
  });

  const patch = useMutation({
    // driver_id: null unassigns (the API distinguishes null from absent).
    mutationFn: (body: { state?: OrderState; driver_id?: string | null }) =>
      api.patch<Order>(`/api/orders/${order.id}`, body),
    onSuccess: invalidate,
  });

  const eta = useMutation({
    mutationFn: () =>
      api.get<{ eta_seconds: number; distance_m: number; geometry: RouteGeometry }>(
        `/api/orders/${order.id}/eta`,
      ),
    onSuccess: (data) => {
      onShowRoute(data.geometry);
      invalidate();
    },
  });

  return (
    <div className="space-y-3">
      <button onClick={onBack} className="text-xs text-sky-400 hover:underline">
        ← All orders
      </button>
      <div className="rounded-lg bg-slate-800 p-3 text-sm">
        <p className="font-medium text-white">{order.delivery_address}</p>
        <dl className="mt-2 space-y-1 text-xs text-slate-300">
          <div className="flex justify-between">
            <dt>Pickup</dt>
            <dd className="truncate pl-2">{order.pickup_address}</dd>
          </div>
          <div className="flex justify-between">
            <dt>State</dt>
            <dd>{order.state}</dd>
          </div>
          <div className="flex justify-between">
            <dt>ETA</dt>
            <dd>{formatDuration(order.eta_seconds)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Geofence</dt>
            <dd>{formatDistance(order.geofence_meters)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Promised</dt>
            <dd>{formatTime(order.promised_at)}</dd>
          </div>
        </dl>
      </div>

      <div className="space-y-2">
        <label className="block text-xs text-slate-400">
          Driver
          <select
            value={order.driver_id ?? ""}
            onChange={(e) =>
              patch.mutate(
                e.target.value
                  ? { driver_id: e.target.value, state: "assigned" }
                  : { driver_id: null },
              )
            }
            disabled={order.state !== "created" && order.state !== "assigned"}
            className="mt-1 w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white"
          >
            <option value="">Unassigned</option>
            {drivers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.vehicle_type})
              </option>
            ))}
          </select>
        </label>

        <div className="flex flex-wrap gap-2">
          {(NEXT_STATES[order.state] ?? []).map((next) => (
            <button
              key={next}
              onClick={() => patch.mutate({ state: next })}
              className="rounded-md bg-slate-700 px-3 py-1.5 text-xs text-white hover:bg-slate-600"
            >
              Mark {next.replace("_", " ")}
            </button>
          ))}
          <button
            onClick={() => eta.mutate()}
            disabled={eta.isPending}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {eta.isPending ? "Routing…" : "Show route + ETA"}
          </button>
        </div>
        {patch.isError && (
          <p className="text-xs text-red-400">{(patch.error as Error).message}</p>
        )}
        {eta.isError && <p className="text-xs text-red-400">{(eta.error as Error).message}</p>}
      </div>

      <div>
        <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Geofence events
        </h3>
        <ul className="mt-1 space-y-1 text-xs text-slate-300">
          {(events.data ?? []).map((ev) => (
            <li key={ev.id} className="flex justify-between">
              <span>{ev.kind}</span>
              <span className="text-slate-500">{formatTime(ev.occurred_at)}</span>
            </li>
          ))}
          {events.data?.length === 0 && <li className="text-slate-500">None yet.</li>}
        </ul>
      </div>
    </div>
  );
}
