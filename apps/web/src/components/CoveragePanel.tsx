import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import type { Coverage } from "../lib/api";
import { api } from "../lib/api";
import type { CoverageFeatureProps } from "../lib/coverage";
import { coverageToGeoJSON } from "../lib/coverage";

export interface CoverageSettings {
  resolution: number;
  kind: "pickup" | "delivery";
  days: number | null; // null = all time
}

interface Props {
  settings: CoverageSettings;
  onChange: (settings: CoverageSettings) => void;
  onData: (
    geojson: GeoJSON.FeatureCollection<GeoJSON.Polygon, CoverageFeatureProps> | null,
  ) => void;
}

export function CoveragePanel({ settings, onChange, onData }: Props) {
  const params = new URLSearchParams({
    resolution: String(settings.resolution),
    kind: settings.kind,
  });
  if (settings.days !== null) {
    params.set(
      "from",
      new Date(Date.now() - settings.days * 24 * 3600 * 1000).toISOString(),
    );
  }

  const coverage = useQuery({
    queryKey: ["coverage", settings],
    queryFn: () => api.get<Coverage>(`/api/analytics/coverage?${params}`),
  });

  useEffect(() => {
    onData(coverage.data ? coverageToGeoJSON(coverage.data.cells) : null);
  }, [coverage.data, onData]);

  // Clear the hex layer when leaving the tab.
  useEffect(() => () => onData(null), [onData]);

  return (
    <div className="space-y-3">
      <label className="block text-xs text-slate-400">
        Resolution ({settings.resolution})
        <input
          type="range"
          min={7}
          max={9}
          value={settings.resolution}
          onChange={(e) => onChange({ ...settings, resolution: Number(e.target.value) })}
          className="mt-1 w-full"
        />
      </label>

      <label className="block text-xs text-slate-400">
        Endpoint
        <select
          value={settings.kind}
          onChange={(e) =>
            onChange({ ...settings, kind: e.target.value as CoverageSettings["kind"] })
          }
          className="mt-1 w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white"
        >
          <option value="pickup">Pickups</option>
          <option value="delivery">Deliveries</option>
        </select>
      </label>

      <label className="block text-xs text-slate-400">
        Time range
        <select
          value={settings.days ?? "all"}
          onChange={(e) =>
            onChange({
              ...settings,
              days: e.target.value === "all" ? null : Number(e.target.value),
            })
          }
          className="mt-1 w-full rounded-md bg-slate-700 px-2 py-1.5 text-sm text-white"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value="all">All time</option>
        </select>
      </label>

      {coverage.data && (
        <p className="text-xs text-slate-400">
          {coverage.data.total_orders} orders across {coverage.data.cells.length} hexes
        </p>
      )}

      <div className="rounded-lg bg-slate-800 p-3 text-xs text-slate-400">
        <p className="font-medium text-slate-300">Color scale</p>
        <p className="mt-1">
          Order density per hex, normalized to the densest cell: pale amber (sparse) → orange →
          deep red (dense). Empty hexes aren't drawn.
        </p>
      </div>
    </div>
  );
}
