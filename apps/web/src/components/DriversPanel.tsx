import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Driver, OptimizeResult, Order } from "../lib/api";
import { api } from "../lib/api";
import { formatDistance, formatDuration, formatTime } from "../lib/format";

interface Props {
  drivers: Driver[];
  orders: Order[];
  selectedDriverId: string | null;
  onSelect: (driverId: string | null) => void;
  onShowRoute: (line: GeoJSON.LineString | null) => void;
}

export function DriversPanel({ drivers, orders, selectedDriverId, onSelect, onShowRoute }: Props) {
  const selected = drivers.find((d) => d.id === selectedDriverId) ?? null;
  return selected ? (
    <DriverDetail
      driver={selected}
      orders={orders}
      onBack={() => {
        onSelect(null);
        onShowRoute(null);
      }}
      onShowRoute={onShowRoute}
    />
  ) : (
    <div className="space-y-4">
      <ul className="space-y-2">
        {drivers.length === 0 && <p className="text-sm text-slate-400">No drivers yet.</p>}
        {drivers.map((driver) => (
          <li key={driver.id}>
            <button
              onClick={() => onSelect(driver.id)}
              className="w-full rounded-lg bg-slate-800 p-3 text-left hover:bg-slate-700"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm text-white">{driver.name}</span>
                <span className="text-xs text-slate-400">{driver.state}</span>
              </div>
              <div className="mt-1 text-xs text-slate-400">
                {driver.vehicle_type} ·{" "}
                {driver.current_location_updated_at
                  ? `seen ${formatTime(driver.current_location_updated_at)}`
                  : "no location"}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <NewDriverForm />
    </div>
  );
}

function DriverDetail({
  driver,
  orders,
  onBack,
  onShowRoute,
}: {
  driver: Driver;
  orders: Order[];
  onBack: () => void;
  onShowRoute: (line: GeoJSON.LineString | null) => void;
}) {
  const [plan, setPlan] = useState<OptimizeResult | null>(null);
  const assigned = orders.filter(
    (o) => o.driver_id === driver.id && ["assigned", "picked_up"].includes(o.state),
  );

  const optimize = useMutation({
    mutationFn: () => api.post<OptimizeResult>(`/api/drivers/${driver.id}/optimize`),
    onSuccess: (result) => {
      setPlan(result);
      const coordinates: [number, number][] = [
        ...(driver.current_location
          ? [[driver.current_location.lng, driver.current_location.lat] as [number, number]]
          : []),
        ...result.stops.map((s) => [s.lng, s.lat] as [number, number]),
      ];
      onShowRoute({ type: "LineString", coordinates });
    },
  });

  return (
    <div className="space-y-3">
      <button onClick={onBack} className="text-xs text-sky-400 hover:underline">
        ← All drivers
      </button>
      <div className="rounded-lg bg-slate-800 p-3 text-sm">
        <p className="font-medium text-white">{driver.name}</p>
        <dl className="mt-2 space-y-1 text-xs text-slate-300">
          <div className="flex justify-between">
            <dt>Vehicle</dt>
            <dd>{driver.vehicle_type}</dd>
          </div>
          <div className="flex justify-between">
            <dt>State</dt>
            <dd>{driver.state}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Phone</dt>
            <dd>{driver.phone}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Active orders</dt>
            <dd>{assigned.length}</dd>
          </div>
        </dl>
      </div>

      <button
        onClick={() => optimize.mutate()}
        disabled={optimize.isPending || assigned.length === 0}
        className="w-full rounded-md bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        {optimize.isPending ? "Optimizing…" : `Optimize route (${assigned.length} orders)`}
      </button>
      {optimize.isError && (
        <p className="text-xs text-red-400">{(optimize.error as Error).message}</p>
      )}

      {plan && (
        <div className="rounded-lg bg-slate-800 p-3">
          <p className="text-xs text-slate-300">
            {formatDuration(plan.total_duration_s)} · {formatDistance(plan.total_distance_m)}
          </p>
          <ol className="mt-2 space-y-1 text-xs text-slate-300">
            {plan.stops.map((stop, index) => (
              <li key={`${stop.order_id}-${stop.kind}`} className="flex justify-between">
                <span>
                  {index + 1}. {stop.kind === "pickup" ? "Pick up" : "Deliver"}
                </span>
                <span className="text-slate-500">+{formatDuration(stop.arrival_offset_s)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function NewDriverForm() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [vehicle, setVehicle] = useState<Driver["vehicle_type"]>("bike");

  const create = useMutation({
    mutationFn: () =>
      api.post<Driver>("/api/drivers", { name, phone, vehicle_type: vehicle }),
    onSuccess: () => {
      setName("");
      setPhone("");
      void queryClient.invalidateQueries({ queryKey: ["drivers"] });
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
      className="space-y-2 rounded-lg bg-slate-800 p-3"
    >
      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
        Register driver
      </h3>
      <input
        required
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white placeholder-slate-400"
      />
      <input
        required
        placeholder="Phone"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        className="w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white placeholder-slate-400"
      />
      <select
        value={vehicle}
        onChange={(e) => setVehicle(e.target.value as Driver["vehicle_type"])}
        className="w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white"
      >
        <option value="bike">Bike</option>
        <option value="scooter">Scooter</option>
        <option value="car">Car</option>
        <option value="van">Van</option>
      </select>
      <button
        type="submit"
        disabled={create.isPending}
        className="w-full rounded-md bg-sky-600 py-1.5 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
      >
        Add driver
      </button>
      {create.isError && (
        <p className="text-xs text-red-400">{(create.error as Error).message}</p>
      )}
    </form>
  );
}
