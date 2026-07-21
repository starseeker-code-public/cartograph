/** H3 coverage cells → GeoJSON for the map's fill layer.
 *
 * Color scale (documented per Phase 8 DoD): a hex's `intensity` is its order
 * count normalized by the densest cell (0..1]; the map layer interpolates
 * from pale amber (sparse) to deep red (dense). Empty cells aren't drawn.
 */

import { cellToBoundary } from "h3-js";
import type { CoverageCell } from "./api";

export interface CoverageFeatureProps {
  hex: string;
  count: number;
  intensity: number;
}

export function coverageToGeoJSON(
  cells: CoverageCell[],
): GeoJSON.FeatureCollection<GeoJSON.Polygon, CoverageFeatureProps> {
  const max = Math.max(1, ...cells.map((c) => c.count));
  return {
    type: "FeatureCollection",
    features: cells.map((cell) => ({
      type: "Feature",
      properties: {
        hex: cell.hex,
        count: cell.count,
        intensity: cell.count / max,
      },
      geometry: {
        type: "Polygon",
        // h3-js returns [lat, lng]; GeoJSON wants [lng, lat].
        coordinates: [cellToBoundary(cell.hex).map(([lat, lng]) => [lng, lat])],
      },
    })),
  };
}
