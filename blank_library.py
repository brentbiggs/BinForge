#!/usr/bin/env python3
"""
BinForge Maintainable Blank Library (Declarative JSON Presets + Pluggable 3D CAD Styles)

How to maintain or add new bin blanks:
1. Adding/tweaking bin dimensions (no Python required):
   Edit `blanks.json` to adjust dimensions (`plate_w`, `plate_h`, `plate_z`, `wing_w`, etc.)
   or add a new entry referencing an existing style (`"cullenect_groove"`, `"akro_slot"`,
   `"gladiator_slot"`, or `"flat_plate"`).

2. Adding a brand-new 3D blank geometry style (in this file):
   Decorate a builder function with `@register_blank_style("my_style")`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from build123d import *

DEFAULT_BLANKS_JSON = Path(__file__).resolve().parent / "blanks.json"
MESH_LINEAR_DEFLECTION = 0.02
MESH_ANGULAR_DEFLECTION = 0.20


def _premesh_blank(shape: Shape) -> None:
    """Attach FDM-resolution Poly_Triangulation to blank faces so .moved() copies share it."""
    try:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh

        BRepMesh_IncrementalMesh(
            shape.wrapped,
            MESH_LINEAR_DEFLECTION,
            False,
            MESH_ANGULAR_DEFLECTION,
            True,
        )
    except Exception:
        pass


@dataclass(frozen=True)
class BlankSpec:
    """Immutable geometric specification for a resolved bin label blank."""

    name: str
    style: str
    plate_w: float
    plate_h: float
    plate_z: float
    corner_r: float
    wing_w: float = 0.0
    wing_z: float = 0.0
    latch_inset: float = 0.20
    latch_z_pos: float = 0.40
    latch_h: float = 0.40
    description: str = ""

    @property
    def visible_w(self) -> float:
        """Width of the raised front face unobstructed by side retention wings."""
        return self.plate_w - (2.0 * self.wing_w)


# ============================================================================
# Pluggable 3D Blank Style Registry
# ============================================================================

BLANK_STYLE_BUILDERS: dict[str, Callable[[BlankSpec, Sketch], Part]] = {}


def register_blank_style(
    style_name: str,
) -> Callable[[Callable[[BlankSpec, Sketch], Part]], Callable[[BlankSpec, Sketch], Part]]:
    """Decorator to register a 3D CAD builder for a blank geometry style."""
    key = style_name.strip().lower()

    def _decorator(
        func: Callable[[BlankSpec, Sketch], Part]
    ) -> Callable[[BlankSpec, Sketch], Part]:
        BLANK_STYLE_BUILDERS[key] = func
        return func

    return _decorator


@register_blank_style("flat_plate")
def _build_flat_plate(spec: BlankSpec, outer_sketch: Sketch) -> Part:
    """Simple rounded flat plate (for magnetic, adhesive, or drop-in holders)."""
    with BuildPart() as base_part:
        extrude(outer_sketch, amount=spec.plate_z)
    return base_part.part


@register_blank_style("cullenect_groove")
def _build_cullenect_groove(spec: BlankSpec, outer_sketch: Sketch) -> Part:
    """Gridfinity Cullenect blank with top and bottom horizontal retention grooves."""
    latch_plane = Plane.XY.offset(spec.latch_z_pos)
    with BuildPart() as base_part:
        extrude(outer_sketch, amount=spec.plate_z)
        # Cut retention grooves along top and bottom long edges only,
        # leaving a 2-layer bottom lip and full-strength side walls.
        with BuildSketch(latch_plane):
            Rectangle(spec.plate_w + 4.0, spec.plate_h + 4.0)
            Rectangle(
                spec.plate_w + 4.0,
                spec.plate_h - (2.0 * spec.latch_inset),
                mode=Mode.SUBTRACT,
            )
        extrude(amount=spec.latch_h, mode=Mode.SUBTRACT)
    return base_part.part


@register_blank_style("akro_slot")
def _build_akro_slot(spec: BlankSpec, outer_sketch: Sketch) -> Part:
    """Akro-Mils slide-in blank with stepped left/right retention wings and raised center island."""
    with BuildPart() as base_part:
        extrude(outer_sketch, amount=spec.wing_z)
        with BuildSketch(Plane.XY.offset(spec.wing_z)) as island_sk:
            Rectangle(spec.plate_w, spec.plate_h)
            fillet(vertices(), radius=spec.corner_r)
            Rectangle(
                spec.visible_w,
                spec.plate_h + 2.0,
                mode=Mode.INTERSECT,
            )
        extrude(island_sk.sketch, amount=spec.plate_z - spec.wing_z)
    return base_part.part


@register_blank_style("gladiator_slot")
def _build_gladiator_slot(spec: BlankSpec, outer_sketch: Sketch) -> Part:
    """Gladiator slide-in blank with stepped side rails, raised island, and bottom retention detent."""
    with BuildPart() as base_part:
        extrude(outer_sketch, amount=spec.wing_z)
        with BuildSketch(Plane.XY.offset(spec.wing_z)) as island_sk:
            Rectangle(spec.plate_w, spec.plate_h)
            fillet(vertices(), radius=spec.corner_r)
            with Locations((0.0, spec.latch_inset / 2.0)):
                Rectangle(
                    spec.visible_w,
                    spec.plate_h - spec.latch_inset,
                    mode=Mode.INTERSECT,
                )
        extrude(island_sk.sketch, amount=spec.plate_z - spec.wing_z)
    return base_part.part


# ============================================================================
# Declarative JSON Catalog Loader & Resolver
# ============================================================================


@lru_cache(maxsize=8)
def _load_blanks_catalog_cached(json_path_str: str, mtime_ns: int) -> dict[str, Any]:
    with Path(json_path_str).open("r", encoding="utf-8") as f:
        return json.load(f)


def load_blanks_catalog(
    blanks_file: str | Path = DEFAULT_BLANKS_JSON,
) -> dict[str, Any]:
    """Load the declarative blanks catalog from `blanks.json` (auto-reloads when modified)."""
    path = Path(blanks_file).resolve()
    mtime_ns = path.stat().st_mtime_ns if path.is_file() else 0
    return _load_blanks_catalog_cached(str(path), mtime_ns)


def list_available_blanks(
    blanks_file: str | Path = DEFAULT_BLANKS_JSON,
) -> tuple[str, ...]:
    """Return all valid blank_type names (including aliases) from `blanks.json`."""
    catalog = load_blanks_catalog(blanks_file)
    blanks = list(catalog.get("blanks", {}).keys())
    aliases = list(catalog.get("aliases", {}).keys())
    return tuple(blanks + [a for a in aliases if a not in blanks])


AVAILABLE_BLANK_TYPES: tuple[str, ...] = list_available_blanks()


def resolve_blank_spec(
    blank_type: str,
    blanks_file: str | Path = DEFAULT_BLANKS_JSON,
) -> BlankSpec:
    """Resolve a BlankSpec by blank_type name from `blanks.json`."""
    catalog = load_blanks_catalog(blanks_file)
    blanks_map: dict[str, dict[str, Any]] = catalog.get("blanks", {})
    aliases_map: dict[str, str] = catalog.get("aliases", {})

    norm = blank_type.strip().lower()
    key = aliases_map.get(norm, norm)
    if key not in blanks_map:
        valid = ", ".join(list_available_blanks(blanks_file))
        raise ValueError(f"Unknown blank_type '{blank_type}'. Valid options: {valid}")

    entry = blanks_map[key]
    style = str(entry.get("style", "flat_plate")).strip().lower()
    if style not in BLANK_STYLE_BUILDERS:
        valid_styles = ", ".join(sorted(BLANK_STYLE_BUILDERS.keys()))
        raise ValueError(
            f"Blank '{key}' references unknown style '{style}'. Valid styles: {valid_styles}"
        )

    return BlankSpec(
        name=key,
        style=style,
        plate_w=float(entry["plate_w"]),
        plate_h=float(entry["plate_h"]),
        plate_z=float(entry["plate_z"]),
        corner_r=float(entry.get("corner_r", 1.50)),
        wing_w=float(entry.get("wing_w", 0.0)),
        wing_z=float(entry.get("wing_z", 0.0)),
        latch_inset=float(entry.get("latch_inset", 0.20)),
        latch_z_pos=float(entry.get("latch_z_pos", 0.40)),
        latch_h=float(entry.get("latch_h", 0.40)),
        description=str(entry.get("description", "")),
    )


# ============================================================================
# Cached 2D & 3D Blank Builders
# ============================================================================


@lru_cache(maxsize=64)
def build_blank_sketch(spec: BlankSpec) -> Sketch:
    """Build and cache the 2D top-down plan sketch for a BlankSpec."""
    with BuildSketch() as base_sk:
        Rectangle(spec.plate_w, spec.plate_h)
        fillet(vertices(), radius=spec.corner_r)
        if spec.wing_w > 0.0:
            # Include vertical step lines of the raised center island for 2D plan view clarity
            Rectangle(spec.visible_w, spec.plate_h, mode=Mode.ADD)
    return base_sk.sketch


@lru_cache(maxsize=64)
def build_blank_part(spec: BlankSpec) -> Part:
    """Build, pre-mesh, and cache the 3D solid blank Part for a BlankSpec."""
    with BuildSketch() as outer_sk:
        Rectangle(spec.plate_w, spec.plate_h)
        fillet(vertices(), radius=spec.corner_r)

    builder = BLANK_STYLE_BUILDERS[spec.style]
    part = builder(spec, outer_sk.sketch)
    _premesh_blank(part)
    return part


@lru_cache(maxsize=64)
def project_blank_iso(
    spec: BlankSpec,
    direction: tuple[float, float, float] = (100, -100, 100),
    up: tuple[float, float, float] = (0, 0, 1),
) -> Shape:
    """Memoize 3D HLR isometric projection of the base plate per BlankSpec."""
    blank = build_blank_part(spec)
    base_vis, _ = blank.project_to_viewport(
        viewport_origin=direction, viewport_up=up
    )
    return base_vis


def format_blank_catalog_table(
    blanks_file: str | Path = DEFAULT_BLANKS_JSON,
) -> str:
    """Format a human-readable summary table of all blank presets and aliases."""
    catalog = load_blanks_catalog(blanks_file)
    blanks_map: dict[str, dict[str, Any]] = catalog.get("blanks", {})
    aliases_map: dict[str, str] = catalog.get("aliases", {})

    inv_aliases: dict[str, list[str]] = {}
    for alias, target in aliases_map.items():
        inv_aliases.setdefault(target, []).append(alias)

    lines = [
        f"BinForge Blank Library ({Path(blanks_file).name})",
        "=" * 96,
        f"{'Blank Type':<20} {'Style':<18} {'Outer WxHxZ (mm)':<20} {'Visible W':<11} {'Aliases / Notes'}",
        "-" * 96,
    ]
    for key in blanks_map:
        spec = resolve_blank_spec(key, blanks_file=blanks_file)
        dims = f"{spec.plate_w:.1f}x{spec.plate_h:.1f}x{spec.plate_z:.2f}"
        vis = f"{spec.visible_w:.1f} mm"
        alias_list = inv_aliases.get(key, [])
        alias_str = f"[alias: {', '.join(alias_list)}] " if alias_list else ""
        lines.append(
            f"{key:<20} {spec.style:<18} {dims:<20} {vis:<11} {alias_str}{spec.description}"
        )
    lines.append("-" * 96)
    return "\n".join(lines)
