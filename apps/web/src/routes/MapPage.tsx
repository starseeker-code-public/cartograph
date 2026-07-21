import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";

import { CoveragePanel, type CoverageSettings } from "../components/CoveragePanel";
import { DriversPanel } from "../components/DriversPanel";
import { MapView } from "../components/MapView";
import { OrdersPanel } from "../components/OrdersPanel";
import type { Driver, Order, User } from "../lib/api";
import { api, ApiError } from "../lib/api";
import type { CoverageFeatureProps } from "../lib/coverage";

type Tab = "orders" | "drivers" | "coverage";

export function MapPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("orders");
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [selectedDriverId, setSelectedDriverId] = useState<string | null>(null);
  const [routeLine, setRouteLine] = useState<GeoJSON.LineString | null>(null);
  const [coverage, setCoverage] = useState<GeoJSON.FeatureCollection<
    GeoJSON.Polygon,
    CoverageFeatureProps
  > | null>(null);
  const [coverageSettings, setCoverageSettings] = useState<CoverageSettings>({
    resolution: 8,
    kind: "pickup",
    days: 30,
  });

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/api/auth/me"),
    retry: false,
  });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      void navigate({ to: "/login" });
    }
  }, [me.error, navigate]);

  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => api.get<Order[]>("/api/orders"),
    enabled: me.isSuccess,
    refetchInterval: 10_000,
  });

  // Polling keeps driver pins live (V1; WebSockets are a V3 stretch).
  const drivers = useQuery({
    queryKey: ["drivers"],
    queryFn: () => api.get<Driver[]>("/api/drivers"),
    enabled: me.isSuccess,
    refetchInterval: 5_000,
  });

  const showCoverage = useCallback(
    (data: typeof coverage) => setCoverage(data),
    [],
  );

  if (me.isPending) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-900 text-slate-400">
        Loading…
      </div>
    );
  }
  if (me.isError) return null; // redirecting to /login

  return (
    <div className="flex h-full bg-slate-900">
      <aside className="flex w-80 shrink-0 flex-col border-r border-slate-800">
        <header className="flex items-center justify-between px-4 py-3">
          <h1 className="text-lg font-semibold text-white">Cartograph</h1>
          <button
            onClick={async () => {
              await api.post("/api/auth/logout");
              await navigate({ to: "/login" });
            }}
            className="text-xs text-slate-400 hover:text-white"
          >
            Sign out
          </button>
        </header>

        <nav className="flex gap-1 px-4">
          {(["orders", "drivers", "coverage"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-t-md px-3 py-1.5 text-sm capitalize ${
                tab === t
                  ? "bg-slate-800 text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {t}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-y-auto bg-slate-800/40 p-4">
          {tab === "orders" && (
            <OrdersPanel
              orders={orders.data ?? []}
              drivers={drivers.data ?? []}
              selectedOrderId={selectedOrderId}
              onSelect={setSelectedOrderId}
              onShowRoute={setRouteLine}
            />
          )}
          {tab === "drivers" && (
            <DriversPanel
              drivers={drivers.data ?? []}
              orders={orders.data ?? []}
              selectedDriverId={selectedDriverId}
              onSelect={setSelectedDriverId}
              onShowRoute={setRouteLine}
            />
          )}
          {tab === "coverage" && (
            <CoveragePanel
              settings={coverageSettings}
              onChange={setCoverageSettings}
              onData={showCoverage}
            />
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <MapView
          orders={orders.data ?? []}
          drivers={drivers.data ?? []}
          coverage={coverage}
          routeLine={routeLine}
          onSelectOrder={(id) => {
            setTab("orders");
            setSelectedOrderId(id);
          }}
          onSelectDriver={(id) => {
            setTab("drivers");
            setSelectedDriverId(id);
          }}
        />
      </main>
    </div>
  );
}
