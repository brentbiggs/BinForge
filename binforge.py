#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from build123d import *

from blank_library import (
    AVAILABLE_BLANK_TYPES,
    DEFAULT_BLANKS_JSON,
    BlankSpec,
    build_blank_part,
    build_blank_sketch,
    format_blank_catalog_table,
    list_available_blanks,
    project_blank_iso,
    resolve_blank_spec,
)
from icon_library import (
    DEFAULT_ICONS_DIR,
    ICON_ALIASES,
    ICON_METADATA_REGISTRY,
    PROCEDURAL_ICON_REGISTRY,
    export_icon_catalog_svg,
    format_icon_catalog_table,
    get_unit_icon,
    is_valid_icon,
    list_available_icons,
    register_icon,
)

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
__version__ = (
    VERSION_FILE.read_text(encoding="utf-8").strip()
    if VERSION_FILE.is_file()
    else "0.1.0"
)

MESH_LINEAR_DEFLECTION = 0.02
MESH_ANGULAR_DEFLECTION = 0.20


def _default_font() -> str:
    return "Arial" if platform.system() == "Windows" else "Liberation Sans"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _center_sketch(sk: Sketch) -> Sketch:
    bbox = sk.bounding_box()
    cx = (bbox.min.X + bbox.max.X) / 2.0
    cy = (bbox.min.Y + bbox.max.Y) / 2.0
    return sk.moved(Location((-cx, -cy, 0.0)))


def _premesh_shape(shape: Shape) -> None:
    """Attach FDM-resolution Poly_Triangulation to shape faces so .moved() copies share it."""
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


def _add_to_mesher(mesher: Mesher, shape: Shape) -> None:
    try:
        mesher.add_shape(
            shape,
            linear_deflection=MESH_LINEAR_DEFLECTION,
            angular_deflection=MESH_ANGULAR_DEFLECTION,
        )
    except TypeError:
        mesher.add_shape(shape)


def _pack_into_single_solid(
    solids: list[Solid], label: str, color: Color
) -> Shape:
    """Pack disjoint solids into a single multi-shell Solid so .3mf Mesher emits 1 object."""
    if not solids:
        return Compound(label=label, color=color)
    if len(solids) == 1:
        return Solid(solids[0].wrapped, label=label, color=color)
    try:
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Solid

        builder = BRep_Builder()
        ocp_solid = TopoDS_Solid()
        builder.MakeSolid(ocp_solid)
        for s in solids:
            for shell in s.shells():
                builder.Add(ocp_solid, shell.wrapped)
        return Solid(ocp_solid, label=label, color=color)
    except Exception:
        return Compound(children=solids, label=label, color=color)


AVAILABLE_ICONS: tuple[str, ...] = tuple(sorted(PROCEDURAL_ICON_REGISTRY.keys())) + (
    "none",
)

_cached_base_sketch = build_blank_sketch
_cached_blank = build_blank_part
_cached_base_iso_projection = project_blank_iso


def _cached_unit_icon(name: str) -> Optional[Sketch]:
    return get_unit_icon(name)


@lru_cache(maxsize=64)
def _cached_icon_solids(
    name: str, dim: float, art_thickness: float
) -> tuple[Solid, ...]:
    """Memoize and pre-mesh 3D extruded icon solids centered at the origin."""
    unit_icon = _cached_unit_icon(name)
    if unit_icon is None:
        return ()
    scaled = unit_icon.scale(dim * 0.90)
    solids = tuple(
        extrude(face, amount=art_thickness, clean=False)
        for face in scaled.faces()
    )
    for s in solids:
        _premesh_shape(s)
    return solids


@lru_cache(maxsize=256)
def _cached_fit_text(
    txt: str,
    font_family: str,
    max_w: float,
    init_font_size: float,
    min_font_size: float = 2.0,
) -> Optional[Sketch]:
    clean = txt.strip()
    if not clean:
        return None
    with BuildSketch() as base_sk:
        Text(
            clean,
            font_size=init_font_size,
            font=font_family,
            font_style=FontStyle.BOLD,
            align=(Align.CENTER, Align.CENTER),
        )
    sk = base_sk.sketch
    width = sk.bounding_box().size.X
    if width > max_w and width > 0:
        sk = sk.scale(max_w / width)
    return _center_sketch(sk)


@dataclass
class BinForgeConfig:
    blank_type: str = "cullenect_1u"
    title: str = "M3 x 12"
    subtitle: str = "BHCS"
    icon: str = "bolt"
    drive_icon: str = "none"
    font_family: str = field(default_factory=_default_font)
    target_title_h: float = 4.2
    target_sub_h: float = 2.8
    art_thickness: float = 0.40  # 2 layers at 0.20 mm layer height for opaque contrast
    margin_x: float = 2.4
    margin_y: float = 1.0
    slot_gap: float = 1.5

    def __post_init__(self) -> None:
        resolve_blank_spec(self.blank_type)
        drv = self.drive_icon.strip() if self.drive_icon else "none"
        if drv and drv.lower() != "none":
            base = self.icon.strip() if self.icon else "none"
            if base and base.lower() != "none" and "+" not in base:
                self.icon = f"{base}+{drv}"
            elif not base or base.lower() == "none":
                self.icon = drv


class BinForgeEngine:
    def __init__(self, config: BinForgeConfig):
        self.cfg = config
        self.blank_spec = resolve_blank_spec(config.blank_type)
        self.plate_w = self.blank_spec.plate_w
        self.plate_h = self.blank_spec.plate_h
        self.plate_z = self.blank_spec.plate_z
        self.corner_r = self.blank_spec.corner_r

        # Usable canvas sits inside the unobstructed center island (visible_w)
        self.usable_w = self.blank_spec.visible_w - (2.0 * config.margin_x)
        self.usable_h = self.plate_h - (2.0 * config.margin_y)

        # Scale typography proportionally on taller bin blanks (e.g. Akro-Mils / Gladiator)
        # when using standard 11mm-baseline font heights.
        self.height_scale = max(1.0, self.usable_h / 9.0)
        self.effective_title_h = (
            config.target_title_h * self.height_scale
            if config.target_title_h == 4.2
            else config.target_title_h
        )
        self.effective_sub_h = (
            config.target_sub_h * self.height_scale
            if config.target_sub_h == 2.8
            else config.target_sub_h
        )
        self._orchestrate_layout()

    def _orchestrate_layout(self):
        has_icon = (
            self.cfg.icon != "none" and _cached_unit_icon(self.cfg.icon) is not None
        )
        max_icon_dim = 7.5 * self.height_scale
        icon_dim = min(self.usable_h, max_icon_dim, self.usable_w * 0.35) if has_icon else 0.0

        if not has_icon:
            self.icon_bounds = None
            self.text_bounds = {
                "x_min": -self.usable_w / 2.0,
                "x_max": self.usable_w / 2.0,
                "w": self.usable_w,
                "h": self.usable_h,
                "center_x": 0.0,
            }
        else:
            left_edge = -self.usable_w / 2.0
            icon_center_x = left_edge + (icon_dim / 2.0)
            text_x_min = left_edge + icon_dim + self.cfg.slot_gap
            text_x_max = self.usable_w / 2.0
            text_w = text_x_max - text_x_min

            self.icon_bounds = {
                "center_x": icon_center_x,
                "center_y": 0.0,
                "size": icon_dim,
            }
            self.text_bounds = {
                "x_min": text_x_min,
                "x_max": text_x_max,
                "w": text_w,
                "h": self.usable_h,
                "center_x": text_x_min + (text_w / 2.0),
            }

    def build_base_sketch(self) -> Sketch:
        return _cached_base_sketch(self.blank_spec)

    def build_blank(self) -> Part:
        cached = _cached_blank(self.blank_spec)
        return Part(cached.wrapped)

    def _build_icon_sketch(self) -> Optional[Sketch]:
        if not self.icon_bounds:
            return None
        unit_icon = _cached_unit_icon(self.cfg.icon)
        if unit_icon is None:
            return None
        dim = self.icon_bounds["size"]
        cx, cy = self.icon_bounds["center_x"], self.icon_bounds["center_y"]
        return unit_icon.scale(dim * 0.90).moved(Location((cx, cy, 0.0)))

    def _fit_text_sketch(
        self,
        txt: str,
        max_w: float,
        init_font_size: float,
        min_font_size: float = 2.0,
    ) -> Optional[Sketch]:
        return _cached_fit_text(
            txt,
            self.cfg.font_family,
            round(max_w, 3),
            round(init_font_size, 3),
            round(min_font_size, 3),
        )

    def _build_text_faces(self) -> list[Face]:
        max_w = self.text_bounds["w"]
        center_x = self.text_bounds["center_x"]
        has_title = bool(self.cfg.title and self.cfg.title.strip())
        has_sub = bool(self.cfg.subtitle and self.cfg.subtitle.strip())

        if not has_title and not has_sub:
            return []

        if has_title and not has_sub:
            title_sk = self._fit_text_sketch(
                self.cfg.title, max_w, self.effective_title_h
            )
            if title_sk is None:
                return []
            return list(title_sk.moved(Location((center_x, 0.0, 0.0))).faces())

        if has_sub and not has_title:
            sub_sk = self._fit_text_sketch(
                self.cfg.subtitle, max_w, self.effective_sub_h
            )
            if sub_sk is None:
                return []
            return list(sub_sk.moved(Location((center_x, 0.0, 0.0))).faces())

        title_sk = self._fit_text_sketch(
            self.cfg.title, max_w, self.effective_title_h * 0.90
        )
        sub_sk = self._fit_text_sketch(
            self.cfg.subtitle, max_w, self.effective_sub_h
        )
        if title_sk is None or sub_sk is None:
            active = title_sk or sub_sk
            return (
                list(active.moved(Location((center_x, 0.0, 0.0))).faces())
                if active
                else []
            )

        title_h = title_sk.bounding_box().size.Y
        sub_h = sub_sk.bounding_box().size.Y
        line_gap = min(
            1.4 * self.height_scale,
            max(0.8, (self.usable_h - title_h - sub_h) * 0.35),
        )
        total_h = title_h + line_gap + sub_h

        if total_h > self.usable_h and total_h > 0:
            v_scale = self.usable_h / total_h
            title_sk = title_sk.scale(v_scale)
            sub_sk = sub_sk.scale(v_scale)
            title_h *= v_scale
            sub_h *= v_scale
            line_gap *= v_scale
            total_h = self.usable_h

        title_y = (total_h / 2.0) - (title_h / 2.0)
        sub_y = -(total_h / 2.0) + (sub_h / 2.0)

        placed_title = title_sk.moved(Location((center_x, title_y, 0.0)))
        placed_sub = sub_sk.moved(Location((center_x, sub_y, 0.0)))
        return list(placed_title.faces()) + list(placed_sub.faces())

    def build_artwork(self) -> tuple[list[Face], list[Solid]]:
        """Build 2D artwork faces and 3D extruded solids in a single pass."""
        faces_2d: list[Face] = []
        solids_3d: list[Solid] = []

        if self.icon_bounds:
            icon_sk = self._build_icon_sketch()
            if icon_sk is not None:
                faces_2d.extend(icon_sk.faces())
            cx = self.icon_bounds["center_x"]
            cy = self.icon_bounds["center_y"]
            dim = round(self.icon_bounds["size"], 3)
            thick = round(self.cfg.art_thickness, 3)
            icon_loc = Location((cx, cy, self.plate_z))
            for s in _cached_icon_solids(self.cfg.icon, dim, thick):
                solids_3d.append(s.moved(icon_loc))

        text_faces = self._build_text_faces()
        faces_2d.extend(text_faces)
        z_loc = Location((0.0, 0.0, self.plate_z))
        for face in text_faces:
            solid = extrude(face, amount=self.cfg.art_thickness, clean=False).moved(
                z_loc
            )
            _premesh_shape(solid)
            solids_3d.append(solid)

        return faces_2d, solids_3d


def export_binforge_plan_svg(
    base_sketch: Sketch,
    art_faces: list[Face],
    file_path: str,
):
    """Fast 2D vector export for top-down plan view (bypasses 3D hidden-line removal)."""
    exporter = ExportSVG(scale=1)
    exporter.add_layer(
        "Base",
        line_color=Color(0.43, 0.43, 0.43),
        line_weight=0.25,
    )
    exporter.add_layer(
        "Artwork",
        line_color=Color(0.0, 0.0, 0.0),
        line_weight=0.35,
    )
    exporter.add_shape(base_sketch, layer="Base")
    if art_faces:
        exporter.add_shape(Compound(children=art_faces), layer="Artwork")
    exporter.write(file_path)


def export_binforge_iso_svg(
    engine: BinForgeEngine,
    artwork: Shape,
    has_artwork: bool,
    file_path: str,
    direction: tuple[float, float, float] = (100, -100, 100),
    up: tuple[float, float, float] = (0, 0, 1),
):
    """3D viewport projection for isometric view using cached base-plate HLR."""
    base_vis = _cached_base_iso_projection(
        engine.blank_spec,
        direction,
        up,
    )

    exporter = ExportSVG(scale=1)
    exporter.add_layer(
        "Base",
        line_color=Color(0.43, 0.43, 0.43),
        line_weight=0.25,
    )
    exporter.add_layer(
        "Artwork",
        line_color=Color(0.0, 0.0, 0.0),
        line_weight=0.35,
    )
    exporter.add_shape(base_vis, layer="Base")
    if has_artwork:
        art_vis, _ = artwork.project_to_viewport(
            viewport_origin=direction, viewport_up=up
        )
        exporter.add_shape(art_vis, layer="Artwork")
    exporter.write(file_path)


def generate_binforge_batch(
    inventory: list[BinForgeConfig],
    output_dir: str = "dist",
    max_plate_row_w: float = 180.0,
):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(f"{output_dir}/svg", exist_ok=True)
    os.makedirs(f"{output_dir}/3mf", exist_ok=True)

    base_color = Color(0.15, 0.15, 0.15)
    art_color = Color(0.95, 0.95, 0.95)

    md_lines = [
        "# BinForge Label Batch Manifest",
        "",
        "**Full Build-Plate Batch Files:** `3mf/batch_plate.3mf` | `3mf/batch_plate.step`",
        "",
        "| Plan View | Isometric View | Title | Subtitle | Blank Type |",
        "|-----------|----------------|-------|----------|------------|",
    ]

    plate_base_solids: list[Solid] = []
    plate_art_solids: list[Solid] = []
    seen_slugs: dict[str, int] = {}
    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0
    plate_gap_x = 4.0
    plate_gap_y = 4.0

    for item in inventory:
        engine = BinForgeEngine(item)
        spec_tag = engine.blank_spec.name
        raw_name = f"{item.title}_{item.subtitle}" if item.subtitle else item.title
        name_slug = _slugify(raw_name) or "blank"
        base_slug = f"label_{spec_tag}_{name_slug}"
        seen_slugs[base_slug] = seen_slugs.get(base_slug, 0) + 1
        slug = (
            base_slug
            if seen_slugs[base_slug] == 1
            else f"{base_slug}_{seen_slugs[base_slug]}"
        )

        blank = engine.build_blank()
        blank.label = "Base"
        blank.color = base_color

        art_faces_2d, art_solids = engine.build_artwork()
        for idx, solid in enumerate(art_solids, start=1):
            solid.label = f"Artwork_{idx}"
            solid.color = art_color

        # STEP compound hierarchy (Base + Artwork) and single-solid 3MF packing
        artwork_compound = Compound(
            children=art_solids,
            label="Artwork",
            color=art_color,
        )
        artwork_3mf = _pack_into_single_solid(
            art_solids, label="Artwork", color=art_color
        )
        assembly = Compound(
            children=[blank, artwork_compound],
            label=slug,
        )

        # 1. Export Individual Label (.3mf with strictly 2 objects + .step assembly)
        mesher = Mesher()
        _add_to_mesher(mesher, blank)
        if art_solids:
            _add_to_mesher(mesher, artwork_3mf)
        mesher.write(f"{output_dir}/3mf/{slug}.3mf")
        export_step(assembly, f"{output_dir}/3mf/{slug}.step")

        # 2. Arrange on Master Build Plate (reusing pre-triangulated topological faces)
        if cursor_x > 0.0 and (cursor_x + engine.plate_w) > max_plate_row_w:
            cursor_x = 0.0
            cursor_y -= row_height + plate_gap_y
            row_height = 0.0

        slot_loc = Location((cursor_x + engine.plate_w / 2.0, cursor_y, 0.0))
        plate_base_solids.extend(blank.moved(slot_loc).solids())
        for s in art_solids:
            plate_art_solids.append(s.moved(slot_loc))

        cursor_x += engine.plate_w + plate_gap_x
        row_height = max(row_height, engine.plate_h)

        # 3. Export SVGs (Direct 2D Plan SVG + Cached-Base 3D Isometric SVG)
        export_binforge_plan_svg(
            engine.build_base_sketch(),
            art_faces_2d,
            f"{output_dir}/svg/{slug}_plan.svg",
        )
        export_binforge_iso_svg(
            engine,
            artwork_compound,
            bool(art_solids),
            f"{output_dir}/svg/{slug}_iso.svg",
        )

        # 4. Append to Markdown Catalog
        plan_img = f"<img src='./svg/{slug}_plan.svg' width='120'/>"
        iso_img = f"<img src='./svg/{slug}_iso.svg' width='120'/>"
        md_lines.append(
            f"| {plan_img} | {iso_img} | **{item.title}** | {item.subtitle} | `{spec_tag}` |"
        )

    # Export Combined Build-Plate Batch (.3mf and .step) with 2 global groups (Base & Artwork)
    if plate_base_solids:
        batch_base_3mf = _pack_into_single_solid(
            plate_base_solids, label="Base", color=base_color
        )
        batch_art_3mf = _pack_into_single_solid(
            plate_art_solids, label="Artwork", color=art_color
        )
        batch_mesher = Mesher()
        _add_to_mesher(batch_mesher, batch_base_3mf)
        if plate_art_solids:
            _add_to_mesher(batch_mesher, batch_art_3mf)
        batch_mesher.write(f"{output_dir}/3mf/batch_plate.3mf")

        batch_step_assembly = Compound(
            children=[
                Compound(children=plate_base_solids, label="Base", color=base_color),
                Compound(children=plate_art_solids, label="Artwork", color=art_color),
            ],
            label="binforge_batch_plate",
        )
        export_step(batch_step_assembly, f"{output_dir}/3mf/batch_plate.step")

    with open(f"{output_dir}/catalog.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Batch complete. Open {output_dir}/catalog.md to preview.")


def _parse_binforge_record(raw: dict[str, Any]) -> BinForgeConfig:
    kwargs: dict[str, Any] = {}
    float_fields = {
        "target_title_h",
        "target_sub_h",
        "art_thickness",
        "margin_x",
        "margin_y",
        "slot_gap",
    }
    str_fields = {"blank_type", "title", "subtitle", "icon", "drive_icon", "font_family"}

    for key, val in raw.items():
        if val is None:
            continue
        k = key.strip()
        if isinstance(val, str):
            val_str = val.strip()
            if val_str == "" and k not in {"title", "subtitle"}:
                continue
        else:
            val_str = str(val)

        if k in float_fields:
            kwargs[k] = float(val)
        elif k in str_fields:
            kwargs[k] = val if isinstance(val, str) else str(val)

    return BinForgeConfig(**kwargs)


def load_binforge_inventory(file_path: str | os.PathLike) -> list[BinForgeConfig]:
    """Load a list of BinForgeConfig items from a .csv or .json inventory file."""
    path = Path(file_path)
    if not path.is_file() and not path.is_absolute():
        alt = Path(__file__).resolve().parent / path
        if alt.is_file():
            path = alt
    ext = path.suffix.lower()
    if ext == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        records = data["labels"] if isinstance(data, dict) and "labels" in data else data
        return [_parse_binforge_record(rec) for rec in records]
    if ext == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [_parse_binforge_record(row) for row in reader]
    raise ValueError(f"Unsupported inventory format '{ext}'. Use .csv or .json.")


@dataclass
class BinForgeItemReport:
    index: int
    slug: str
    blank_name: str
    dimensions_mm: tuple[float, float, float]
    rendered_title_h: float
    rendered_sub_h: float
    warnings: list[str]


@dataclass
class BinForgeLintReport:
    items: list[BinForgeItemReport]
    plate_width_mm: float
    plate_depth_mm: float
    plate_rows: int

    @property
    def total_warnings(self) -> int:
        return sum(len(item.warnings) for item in self.items)

    def format_summary(self) -> str:
        lines = [
            f"BinForge Dry-Run / Lint Report ({len(self.items)} labels)",
            "=" * 88,
            f"{'#':<3} {'Slug':<38} {'Blank':<16} {'Size (mm)':<16} {'Title/Sub H':<12}",
            "-" * 88,
        ]
        for it in self.items:
            w, h, z = it.dimensions_mm
            size_str = f"{w:.0f}x{h:.0f}x{z:.1f}"
            th_str = f"{it.rendered_title_h:.2f}/{it.rendered_sub_h:.2f}"
            lines.append(
                f"{it.index:<3} {it.slug[:37]:<38} {it.blank_name:<16} {size_str:<16} {th_str:<12}"
            )
            for warn in it.warnings:
                lines.append(f"    [WARN] {warn}")
        lines.append("-" * 88)
        lines.append(
            f"Master Build Plate: {self.plate_width_mm:.1f} x {self.plate_depth_mm:.1f} mm "
            f"({self.plate_rows} row{'s' if self.plate_rows != 1 else ''}) | "
            f"Warnings: {self.total_warnings}"
        )
        return "\n".join(lines)


def lint_binforge_inventory(
    inventory: list[BinForgeConfig],
    max_plate_row_w: float = 180.0,
) -> BinForgeLintReport:
    """Fast 2D dry-run and printability linter (skips 3D extrusion, meshing, STEP, and SVG I/O)."""
    items_report: list[BinForgeItemReport] = []
    seen_slugs: dict[str, int] = {}
    cursor_x = 0.0
    row_height = 0.0
    max_used_w = 0.0
    total_depth = 0.0
    plate_rows = 1 if inventory else 0
    plate_gap_x = 4.0
    plate_gap_y = 4.0

    for idx, item in enumerate(inventory, start=1):
        warnings: list[str] = []
        engine = BinForgeEngine(item)
        spec_tag = engine.blank_spec.name
        raw_name = f"{item.title}_{item.subtitle}" if item.subtitle else item.title
        name_slug = _slugify(raw_name) or "blank"
        base_slug = f"label_{spec_tag}_{name_slug}"
        seen_slugs[base_slug] = seen_slugs.get(base_slug, 0) + 1
        if seen_slugs[base_slug] == 1:
            slug = base_slug
        else:
            slug = f"{base_slug}_{seen_slugs[base_slug]}"
            warnings.append(
                f"Duplicate slug '{base_slug}' auto-renamed to '{slug}'."
            )

        if not is_valid_icon(item.icon):
            catalog = list_available_icons()
            valid_list = ", ".join(catalog["procedural"] + catalog["svg"] + ["none"])
            warnings.append(
                f"Unknown icon '{item.icon}' (valid: {valid_list}); falling back to no icon."
            )

        if item.art_thickness < 0.30:
            warnings.append(
                f"art_thickness ({item.art_thickness:.2f} mm) is < 0.30 mm (1 layer at 0.20 mm height may look translucent)."
            )

        if engine.plate_w > max_plate_row_w:
            warnings.append(
                f"Plate width ({engine.plate_w:.1f} mm) exceeds max_plate_row_w ({max_plate_row_w:.1f} mm)."
            )

        max_w = engine.text_bounds["w"]
        has_title = bool(item.title and item.title.strip())
        has_sub = bool(item.subtitle and item.subtitle.strip())
        title_h = 0.0
        sub_h = 0.0

        if has_title and not has_sub:
            t_sk = engine._fit_text_sketch(item.title, max_w, engine.effective_title_h)
            if t_sk is not None:
                title_h = t_sk.bounding_box().size.Y
        elif has_sub and not has_title:
            s_sk = engine._fit_text_sketch(item.subtitle, max_w, engine.effective_sub_h)
            if s_sk is not None:
                sub_h = s_sk.bounding_box().size.Y
        elif has_title and has_sub:
            t_sk = engine._fit_text_sketch(
                item.title, max_w, engine.effective_title_h * 0.90
            )
            s_sk = engine._fit_text_sketch(item.subtitle, max_w, engine.effective_sub_h)
            if t_sk is not None:
                title_h = t_sk.bounding_box().size.Y
            if s_sk is not None:
                sub_h = s_sk.bounding_box().size.Y
            line_gap = min(
                1.4 * engine.height_scale,
                max(0.8, (engine.usable_h - title_h - sub_h) * 0.35),
            )
            total_h = title_h + line_gap + sub_h
            if total_h > engine.usable_h and total_h > 0:
                v_scale = engine.usable_h / total_h
                title_h *= v_scale
                sub_h *= v_scale

        if has_title and title_h < 1.80:
            warnings.append(
                f"Title shrinks to {title_h:.2f} mm height (< 1.80 mm recommended for 0.4 mm nozzle)."
            )
        if has_sub and sub_h < 1.60:
            warnings.append(
                f"Subtitle shrinks to {sub_h:.2f} mm height (< 1.60 mm recommended for 0.4 mm nozzle)."
            )
        if not has_title and not has_sub and engine.icon_bounds is None:
            warnings.append("Label has no text or icon (will generate a blank plate).")

        # Track build plate layout footprint
        if cursor_x > 0.0 and (cursor_x + engine.plate_w) > max_plate_row_w:
            total_depth += row_height + plate_gap_y
            cursor_x = 0.0
            row_height = 0.0
            plate_rows += 1

        cursor_x += engine.plate_w + plate_gap_x
        max_used_w = max(max_used_w, cursor_x - plate_gap_x)
        row_height = max(row_height, engine.plate_h)

        items_report.append(
            BinForgeItemReport(
                index=idx,
                slug=slug,
                blank_name=spec_tag,
                dimensions_mm=(engine.plate_w, engine.plate_h, engine.plate_z),
                rendered_title_h=round(title_h, 3),
                rendered_sub_h=round(sub_h, 3),
                warnings=warnings,
            )
        )

    total_depth += row_height
    return BinForgeLintReport(
        items=items_report,
        plate_width_mm=round(max_used_w, 2),
        plate_depth_mm=round(total_depth, 2),
        plate_rows=plate_rows,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BinForge: Generate 3D-printable workshop bin labels (Cullenect, Akro-Mils, Gladiator)."
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"BinForge {__version__}",
        help="Show BinForge version and exit.",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        default=None,
        help="Path to a .csv or .json inventory file (optional).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="dist",
        help="Output directory (default: dist).",
    )
    parser.add_argument(
        "--plate-width",
        type=float,
        default=180.0,
        help="Maximum build-plate row width in mm (default: 180.0).",
    )
    parser.add_argument(
        "--dry-run",
        "--lint",
        dest="dry_run",
        action="store_true",
        help="Validate and lint the inventory (layout, text shrink, nozzle checks, build-plate size) without writing 3D/SVG files.",
    )
    parser.add_argument(
        "--list-icons",
        action="store_true",
        help="List all built-in Mechanical, Electrical, Safety, and external .svg icons.",
    )
    parser.add_argument(
        "--export-icon-catalog",
        nargs="?",
        const=str(DEFAULT_ICONS_DIR / "ICON_CATALOG.svg"),
        default=None,
        metavar="SVG_PATH",
        help="Export a visual SVG contact sheet of the entire icon library (default: icons/ICON_CATALOG.svg).",
    )
    parser.add_argument(
        "--list-blanks",
        action="store_true",
        help="List all configured bin blank presets and aliases from blanks.json.",
    )
    args = parser.parse_args()

    if args.list_blanks:
        print(format_blank_catalog_table())
        raise SystemExit(0)

    if args.list_icons:
        print(format_icon_catalog_table())
        raise SystemExit(0)

    if args.export_icon_catalog:
        catalog_path = export_icon_catalog_svg(args.export_icon_catalog)
        print(f"Exported visual icon catalog SVG to: {catalog_path}")
        raise SystemExit(0)

    if args.input:
        my_inventory = load_binforge_inventory(args.input)
    else:
        my_inventory = [
            BinForgeConfig(
                blank_type="cullenect_1u",
                title="M3 x 8",
                subtitle="SHCS",
                icon="bolt",
            ),
            BinForgeConfig(
                blank_type="cullenect_2u",
                title="10k Resistors",
                subtitle="1/4W 1% Metal Film",
                icon="warning",
            ),
            BinForgeConfig(
                blank_type="akro_30220",
                title="1/4-20 x 1\"",
                subtitle="Hex Cap Grade 8",
                icon="bolt",
            ),
            BinForgeConfig(
                blank_type="gladiator_small",
                title="M6 Flange Nut",
                subtitle="Serrated DIN 6923",
                icon="nut",
            ),
        ]

    if args.dry_run:
        report = lint_binforge_inventory(
            my_inventory, max_plate_row_w=args.plate_width
        )
        print(report.format_summary())
    else:
        generate_binforge_batch(
            my_inventory,
            output_dir=args.output,
            max_plate_row_w=args.plate_width,
        )
