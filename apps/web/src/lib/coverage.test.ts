import { latLngToCell } from "h3-js";
import { describe, expect, it } from "vitest";

import { coverageToGeoJSON } from "./coverage";

describe("coverageToGeoJSON", () => {
  const hexA = latLngToCell(40.4168, -3.7038, 8);
  const hexB = latLngToCell(40.43, -3.68, 8);

  it("builds one closed polygon per cell", () => {
    const fc = coverageToGeoJSON([
      { hex: hexA, count: 4 },
      { hex: hexB, count: 1 },
    ]);
    expect(fc.features).toHaveLength(2);
    for (const feature of fc.features) {
      const ring = feature.geometry.coordinates[0];
      // Hexagon boundary: 6 vertices (h3-js does not repeat the first).
      expect(ring.length).toBeGreaterThanOrEqual(6);
      // GeoJSON [lng, lat] ordering: Madrid is lng≈-3.7, lat≈40.4.
      expect(ring[0][0]).toBeLessThan(0);
      expect(ring[0][1]).toBeGreaterThan(40);
    }
  });

  it("normalizes intensity to the densest cell", () => {
    const fc = coverageToGeoJSON([
      { hex: hexA, count: 4 },
      { hex: hexB, count: 1 },
    ]);
    const byHex = Object.fromEntries(
      fc.features.map((f) => [f.properties.hex, f.properties.intensity]),
    );
    expect(byHex[hexA]).toBe(1);
    expect(byHex[hexB]).toBe(0.25);
  });

  it("handles the empty case", () => {
    expect(coverageToGeoJSON([]).features).toHaveLength(0);
  });
});
