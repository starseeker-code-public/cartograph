import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { Driver, Order } from "../lib/api";
import type { CoverageFeatureProps } from "../lib/coverage";

const MADRID: [number, number] = [-3.7038, 40.4168];

export interface MapViewProps {
  orders: Order[];
  drivers: Driver[];
  coverage: GeoJSON.FeatureCollection<GeoJSON.Polygon, CoverageFeatureProps> | null;
  routeLine: GeoJSON.LineString | null;
  onSelectOrder: (orderId: string) => void;
  onSelectDriver: (driverId: string) => void;
}

function ordersToGeoJSON(orders: Order[]): GeoJSON.FeatureCollection {
  const active = orders.filter((o) =>
    ["created", "assigned", "picked_up"].includes(o.state),
  );
  return {
    type: "FeatureCollection",
    features: active.flatMap((o) => [
      {
        type: "Feature" as const,
        properties: { order_id: o.id, role: "pickup", state: o.state },
        geometry: { type: "Point" as const, coordinates: [o.pickup.lng, o.pickup.lat] },
      },
      {
        type: "Feature" as const,
        properties: { order_id: o.id, role: "delivery", state: o.state },
        geometry: { type: "Point" as const, coordinates: [o.delivery.lng, o.delivery.lat] },
      },
    ]),
  };
}

function driversToGeoJSON(drivers: Driver[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: drivers
      .filter((d) => d.current_location !== null)
      .map((d) => ({
        type: "Feature" as const,
        properties: { driver_id: d.id, name: d.name, state: d.state },
        geometry: {
          type: "Point" as const,
          coordinates: [d.current_location!.lng, d.current_location!.lat],
        },
      })),
  };
}

/** Base OSM raster + tenant vector tiles + live GeoJSON overlays. */
export function MapView({
  orders,
  drivers,
  coverage,
  routeLine,
  onSelectOrder,
  onSelectDriver,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const selectOrderRef = useRef(onSelectOrder);
  const selectDriverRef = useRef(onSelectDriver);
  selectOrderRef.current = onSelectOrder;
  selectDriverRef.current = onSelectDriver;

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: MADRID,
      zoom: 12,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
          cartograph: {
            type: "vector",
            tiles: [`${window.location.origin}/tiles/{z}/{x}/{y}.mvt`],
            minzoom: 0,
            maxzoom: 22,
          },
        },
        layers: [
          { id: "osm", type: "raster", source: "osm" },
          {
            id: "service-areas-fill",
            type: "fill",
            source: "cartograph",
            "source-layer": "service_areas",
            paint: { "fill-color": "#0ea5e9", "fill-opacity": 0.08 },
          },
          {
            id: "service-areas-line",
            type: "line",
            source: "cartograph",
            "source-layer": "service_areas",
            paint: { "line-color": "#0284c7", "line-width": 2 },
          },
          {
            id: "geofences-line",
            type: "line",
            source: "cartograph",
            "source-layer": "geofences",
            paint: {
              "line-color": "#f97316",
              "line-width": 1.5,
              "line-dasharray": [2, 2],
            },
          },
        ],
      },
    });
    mapRef.current = map;

    map.on("load", () => {
      loadedRef.current = true;

      map.addSource("coverage", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "coverage-fill",
        type: "fill",
        source: "coverage",
        paint: {
          // Documented scale: pale amber (sparse) → deep red (dense).
          "fill-color": [
            "interpolate",
            ["linear"],
            ["get", "intensity"],
            0,
            "#fef3c7",
            0.5,
            "#f97316",
            1,
            "#b91c1c",
          ],
          "fill-opacity": 0.45,
        },
      });

      map.addSource("route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        paint: { "line-color": "#6366f1", "line-width": 3, "line-opacity": 0.8 },
      });

      map.addSource("orders", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "order-pins",
        type: "circle",
        source: "orders",
        paint: {
          "circle-radius": 7,
          "circle-color": [
            "match",
            ["get", "role"],
            "pickup",
            "#22c55e",
            "#a855f7",
          ],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      map.addSource("drivers", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "driver-pins",
        type: "circle",
        source: "drivers",
        paint: {
          "circle-radius": 9,
          "circle-color": "#0ea5e9",
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      map.on("click", "order-pins", (event) => {
        const orderId = event.features?.[0]?.properties?.order_id;
        if (typeof orderId === "string") selectOrderRef.current(orderId);
      });
      map.on("click", "driver-pins", (event) => {
        const driverId = event.features?.[0]?.properties?.driver_id;
        if (typeof driverId === "string") selectDriverRef.current(driverId);
      });
      for (const layer of ["order-pins", "driver-pins"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
    });

    return () => {
      loadedRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  function setSourceData(sourceId: string, data: GeoJSON.GeoJSON) {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    const source = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
    source?.setData(data);
  }

  useEffect(() => {
    setSourceData("orders", ordersToGeoJSON(orders));
  }, [orders]);

  useEffect(() => {
    setSourceData("drivers", driversToGeoJSON(drivers));
  }, [drivers]);

  useEffect(() => {
    setSourceData("coverage", coverage ?? { type: "FeatureCollection", features: [] });
  }, [coverage]);

  useEffect(() => {
    setSourceData(
      "route",
      routeLine
        ? { type: "Feature", properties: {}, geometry: routeLine }
        : { type: "FeatureCollection", features: [] },
    );
  }, [routeLine]);

  return <div ref={containerRef} className="h-full w-full" />;
}
