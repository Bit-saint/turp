"""Look up mapped parking lots (and nearby place names) in Overture Maps.

Overture publishes OpenStreetMap-derived data as GeoParquet on a public S3
bucket; parking areas are ``theme=base/type=infrastructure`` with
``class = 'parking'``. Requires ``pyarrow``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from pyproj import Geod

RELEASE = os.environ.get("S1LOT_OVERTURE_RELEASE", "2026-10-21.0")
_BUCKET = "overturemaps-us-west-2"
_GEOD = Geod(ellps="WGS84")


def _fs():
    import pyarrow.fs as pafs
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = {"proxy_options": proxy} if proxy else {}
    return pafs.S3FileSystem(anonymous=True, region="us-west-2", **kw)


def _bbox_filter(lon, lat, radius_m):
    import pyarrow.compute as pc
    dlat = radius_m / 111_320
    dlon = dlat / max(np.cos(np.radians(lat)), 1e-6)
    return ((pc.field("bbox", "xmin") > lon - dlon) & (pc.field("bbox", "xmax") < lon + dlon)
            & (pc.field("bbox", "ymin") > lat - dlat) & (pc.field("bbox", "ymax") < lat + dlat))


@dataclass
class Lot:
    id: str
    name: str | None
    area_ha: float
    geometry: object
    tags: dict

    def feature(self) -> dict:
        from shapely.geometry import mapping
        return {"type": "Feature", "geometry": mapping(self.geometry),
                "properties": {"overture_id": self.id, "name": self.name, "area_ha": round(self.area_ha, 3),
                               **{k: v for k, v in self.tags.items() if v is not None}}}


def find_parking(lon: float, lat: float, radius_m: float = 1500, release: str = RELEASE) -> list[Lot]:
    """Parking polygons whose bbox lies within ``radius_m`` of a point, largest first."""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import shapely.wkb

    d = ds.dataset(f"{_BUCKET}/release/{release}/theme=base/type=infrastructure/", filesystem=_fs(),
                   format="parquet")
    tb = d.to_table(columns=["id", "geometry", "names", "class", "source_tags"],
                    filter=_bbox_filter(lon, lat, radius_m) & (pc.field("class") == "parking"))
    lots = []
    for r in tb.to_pylist():
        g = shapely.wkb.loads(r["geometry"])
        if g.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        tags = dict(r["source_tags"] or {})
        lots.append(Lot(r["id"], (r["names"] or {}).get("primary"),
                        abs(_GEOD.geometry_area_perimeter(g)[0]) / 1e4, g,
                        {k: tags.get(k) for k in ("parking", "access", "operator", "surface", "capacity", "fee")}))
    return sorted(lots, key=lambda l: -l.area_ha)


def nearby_places(lon: float, lat: float, radius_m: float = 300, release: str = RELEASE) -> list[dict]:
    """Named places (shops, venues, ...) near a point, to label a lot."""
    import pyarrow.dataset as ds
    import shapely.wkb

    d = ds.dataset(f"{_BUCKET}/release/{release}/theme=places/type=place/", filesystem=_fs(), format="parquet")
    tb = d.to_table(columns=["names", "basic_category", "addresses", "geometry"],
                    filter=_bbox_filter(lon, lat, radius_m))
    out = []
    for r in tb.to_pylist():
        p = shapely.wkb.loads(r["geometry"])
        dist = _GEOD.inv(lon, lat, p.x, p.y)[2]
        addr = (r["addresses"] or [{}])[0] or {}
        out.append({"name": (r["names"] or {}).get("primary"),
                    "category": r["basic_category"],
                    "address": ", ".join(str(addr[k]) for k in ("freeform", "postcode", "locality") if addr.get(k)),
                    "distance_m": round(dist)})
    return sorted(out, key=lambda x: x["distance_m"])


NATURAL_COVER = ("forest", "grass", "shrub", "crop", "wetland", "moss", "mangrove")


def land_cover(lon_min: float, lat_min: float, lon_max: float, lat_max: float,
               subtypes=NATURAL_COVER, release: str = RELEASE):
    """Union of Overture land-cover polygons (ESA WorldCover-derived) intersecting a box."""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import shapely
    import shapely.wkb
    from shapely.geometry import box

    d = ds.dataset(f"{_BUCKET}/release/{release}/theme=base/type=land_cover/", filesystem=_fs(), format="parquet")
    f = ((pc.field("bbox", "xmax") > lon_min) & (pc.field("bbox", "xmin") < lon_max)
         & (pc.field("bbox", "ymax") > lat_min) & (pc.field("bbox", "ymin") < lat_max)
         & pc.field("subtype").isin(list(subtypes))
         & (pc.field("cartography", "max_zoom") >= 13))  # most detailed level only
    tb = d.to_table(columns=["geometry"], filter=f)
    geoms = [shapely.wkb.loads(g) for g in tb.column("geometry").to_pylist()]
    clip = box(lon_min, lat_min, lon_max, lat_max)
    return shapely.union_all([g.intersection(clip) for g in geoms]) if geoms else None
