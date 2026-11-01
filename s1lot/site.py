"""Site definition: the parking-lot polygon, a reference ring and the output grid."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from pyproj import CRS, Transformer
from rasterio import features
from rasterio.transform import Affine
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


def utm_crs(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


@dataclass
class Site:
    name: str
    lot: object                 # shapely polygon, lon/lat
    exclude: object | None      # shapely geometry (lon/lat) removed from the reference ring
    timezone: str
    elevation_m: float | None   # ellipsoidal height of the lot, for terrain shift correction
    pixel_size: float = 10.0
    buffer_m: float = 400.0     # grid extent around the lot
    ref_inner_m: float = 30.0   # reference ring = lot buffered by [inner, outer]
    ref_outer_m: float = 250.0
    edge_erode_m: float = 10.0  # shrink lot mask to avoid mixing with surroundings
    notes: str = ""
    country: str | None = None       # ISO code for public holidays
    subdivision: str | None = None
    targets: dict | None = None      # options for the point-target analysis
    base_dir: Path | None = None     # directory of the YAML file (relative paths)

    # ---------- construction ----------
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Site":
        path = Path(path)
        cfg = yaml.safe_load(path.read_text())
        lot = _load_geom(cfg["lot"], path.parent)
        exclude = _load_geom(cfg["exclude"], path.parent) if cfg.get("exclude") else None
        keys = ("pixel_size", "buffer_m", "ref_inner_m", "ref_outer_m", "edge_erode_m", "notes",
                "country", "subdivision", "targets")
        return cls(
            name=cfg["name"], lot=lot, exclude=exclude,
            timezone=cfg.get("timezone", "UTC"), elevation_m=cfg.get("elevation_m"),
            base_dir=path.parent, **{k: cfg[k] for k in keys if k in cfg},
        )

    def load_geometry(self, spec):
        """Load an extra geometry referenced from the site file (path or inline GeoJSON)."""
        return _load_geom(spec, self.base_dir or Path("."))

    # ---------- geometry helpers ----------
    @property
    def centroid(self) -> tuple[float, float]:
        c = self.lot.centroid
        return c.x, c.y

    @property
    def crs(self) -> CRS:
        return utm_crs(*self.centroid)

    def to_utm(self, geom):
        t = Transformer.from_crs(4326, self.crs, always_xy=True)
        return shapely.transform(geom, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))

    def grid(self) -> "Grid":
        lot_utm = self.to_utm(self.lot)
        x0, y0, x1, y1 = lot_utm.buffer(self.buffer_m).bounds
        ps = self.pixel_size
        x0, y1 = np.floor(x0 / ps) * ps, np.ceil(y1 / ps) * ps
        w = int(np.ceil((x1 - x0) / ps)); h = int(np.ceil((y1 - y0) / ps))
        return Grid(self.crs, Affine(ps, 0, x0, 0, -ps, y1), w, h)

    def masks(self) -> dict[str, np.ndarray]:
        g = self.grid()
        lot_utm = self.to_utm(self.lot)
        core = lot_utm.buffer(-self.edge_erode_m) if self.edge_erode_m else lot_utm
        if core.is_empty:
            core = lot_utm
        ring = lot_utm.buffer(self.ref_outer_m).difference(lot_utm.buffer(self.ref_inner_m))
        if self.exclude is not None:
            ring = ring.difference(self.to_utm(self.exclude).buffer(self.ref_inner_m))
        return {
            "lot": g.rasterize(core),
            "lot_full": g.rasterize(lot_utm),
            "ref": g.rasterize(ring),
        }

    def bounds_lonlat(self, pad_m: float = 0.0):
        t = Transformer.from_crs(self.crs, 4326, always_xy=True)
        g = self.to_utm(self.lot).buffer(self.buffer_m + pad_m)
        return shapely.transform(g, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))


@dataclass
class Grid:
    crs: CRS
    transform: Affine
    width: int
    height: int

    def rasterize(self, geom) -> np.ndarray:
        if geom.is_empty:
            return np.zeros((self.height, self.width), bool)
        return features.rasterize([(mapping(geom), 1)], out_shape=(self.height, self.width),
                                  transform=self.transform, fill=0, dtype="uint8").astype(bool)

    def lonlat(self) -> tuple[np.ndarray, np.ndarray]:
        """Lon/lat of every pixel centre."""
        cols, rows = np.meshgrid(np.arange(self.width) + 0.5, np.arange(self.height) + 0.5)
        x, y = self.transform @ (cols, rows)
        t = Transformer.from_crs(self.crs, 4326, always_xy=True)
        return t.transform(x, y)

    @property
    def extent(self):
        x0, y1 = self.transform.c, self.transform.f
        return (x0, x0 + self.width * self.transform.a, y1 + self.height * self.transform.e, y1)


def _load_geom(spec, base: Path):
    """A geometry given inline (GeoJSON dict) or as a path to a GeoJSON file."""
    if isinstance(spec, str):
        spec = json.loads((base / spec).read_text())
    if spec.get("type") == "FeatureCollection":
        return unary_union([shape(f["geometry"]) for f in spec["features"]])
    if spec.get("type") == "Feature":
        return shape(spec["geometry"])
    return shape(spec)
