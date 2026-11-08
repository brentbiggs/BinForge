#!/usr/bin/env python3
"""
BinForge Maintainable Icon Library (Procedural Design System + External SVG Support)

Design System & Printability Standards:
- Nominal Canvas: 1.80 x 1.80 units (centered around (0, 0), normalized to 1.0 max span).
- Attach Hardware Views:
  1. Top-Down Drive / Plan Views (`screw_phillips`, `screw_hex`, `screw_torx`, `drive_pozidriv`,
     `drive_external_hex`, `nut`, `nut_lock_top`, `nut_flange_top`, `nut_tnut_top`, `insert_heatset_top`).
  2. Side-Profile Views (`bolt`, `bolt_hex`, `screw_button`, `screw_countersunk`, `screw_pan`,
     `screw_wood`, `set_screw`, `nut_profile`, `nut_lock`, `nut_flange`, `nut_tnut`, `insert_heatset`).
  3. Combined Profile + Drive Views (`shcs_hex`, `shcs_torx`, `bhcs_hex`, `bhcs_torx`,
     `bhcs_phillips`, `fhcs_hex`, `fhcs_torx`, `fhcs_phillips`, `fhcs_slotted`, `pan_phillips`,
     `pan_torx`, `pan_slotted`, `hex_bolt_combo`, `wood_phillips`, `wood_torx`, `wood_square`,
     `set_screw_hex`), plus dynamic `profile+drive` composition (e.g. `icon="screw_button+torx"`).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Callable, Optional
from build123d import *

DEFAULT_ICONS_DIR = Path(__file__).resolve().parent / "icons"

# ============================================================================
# Shared Design-System Tokens (0.4 mm Nozzle Safe across all Blank Sizes)
# ============================================================================
HEAD_R: float = 0.90       # Standard outer radius for round/hex fastener heads
BORE_R: float = 0.44       # Standard inner bore radius for nuts/washers
STROKE_W: float = 0.22     # Primary lead / wall thickness
STROKE_FINE: float = 0.15  # Secondary pin / thread rib thickness
GAP_W: float = 0.22        # Minimum slot / clearance width
LEAD_SPAN: float = 1.80    # Total span of axial component leads
SHANK_W: float = 0.56      # Side-profile fastener shank width
RIB_W: float = 0.84        # Side-profile fastener thread rib width
RIB_H: float = 0.14        # Side-profile fastener thread rib height


@dataclass(frozen=True)
class IconMetadata:
    name: str
    category: str
    description: str
    aliases: tuple[str, ...] = ()


PROCEDURAL_ICON_REGISTRY: dict[str, Callable[[], None]] = {}
ICON_METADATA_REGISTRY: dict[str, IconMetadata] = {}
ICON_ALIASES: dict[str, str] = {}


def register_icon(
    name: str,
    *,
    category: str = "mechanical",
    description: str = "",
    aliases: tuple[str, ...] | list[str] = (),
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Decorator to register a procedural 2D icon builder with category and aliases."""
    key = name.strip().lower()
    alias_tuple = tuple(a.strip().lower() for a in aliases if a.strip())

    def _decorator(func: Callable[[], None]) -> Callable[[], None]:
        doc = description or (func.__doc__ or "").strip().splitlines()[0]
        PROCEDURAL_ICON_REGISTRY[key] = func
        ICON_METADATA_REGISTRY[key] = IconMetadata(
            name=key,
            category=category.strip().lower(),
            description=doc,
            aliases=alias_tuple,
        )
        for alias in alias_tuple:
            ICON_ALIASES[alias] = key
        return func

    return _decorator


def _center_and_normalize_sketch(raw: Sketch) -> Optional[Sketch]:
    bbox = raw.bounding_box()
    max_span = max(bbox.size.X, bbox.size.Y)
    if max_span <= 0:
        return None
    scaled = raw.scale(1.0 / max_span)
    s_bbox = scaled.bounding_box()
    cx = (s_bbox.min.X + s_bbox.max.X) / 2.0
    cy = (s_bbox.min.Y + s_bbox.max.Y) / 2.0
    return scaled.moved(Location((-cx, -cy, 0.0)))


def _add_standard_shank_and_threads() -> None:
    """Shared side-profile fastener shank and 3 symmetric thread ribs."""
    with Locations((0.0, -0.15)):
        Rectangle(SHANK_W, 1.00)
    with Locations((0.0, -0.05), (0.0, -0.30), (0.0, -0.55)):
        Rectangle(RIB_W, RIB_H)


def _add_rounded_polyline(
    points: list[tuple[float, float]], stroke_w: float = STROKE_W
) -> None:
    """
    Draw a continuous round-capped, round-joined path through `points`
    where every segment meets at the exact node coordinates with circular arcs.
    """
    radius = stroke_w / 2.0
    with Locations(*points):
        Circle(radius=radius)
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > 1e-6:
            angle = math.degrees(math.atan2(dy, dx))
            with Locations(((x1 + x2) / 2.0, (y1 + y2) / 2.0)):
                Rectangle(length, stroke_w, rotation=angle)


def _add_combo_profile(profile_kind: str) -> None:
    """
    Draw the left-side fastener profile (at X = -0.44) for combined Profile+Drive icons.
    """
    px = -0.44
    if profile_kind == "shcs":
        with Locations((px, 0.56)):
            Rectangle(0.96, 0.46)
    elif profile_kind == "bhcs":
        with Locations((px, 0.32)):
            Circle(radius=0.58)
        with Locations((px, -0.18)):
            Rectangle(1.30, 1.00, mode=Mode.SUBTRACT)
    elif profile_kind == "fhcs":
        Polygon(
            (px - 0.60, 0.78),
            (px + 0.60, 0.78),
            (px + 0.23, 0.32),
            (px - 0.23, 0.32),
            align=None,
        )
    elif profile_kind == "pan":
        with Locations((px, 0.52)):
            Rectangle(1.04, 0.38)
        with Locations((px, 0.56)):
            Rectangle(0.84, 0.36)
    elif profile_kind == "hex_bolt":
        with Locations((px, 0.58)):
            Rectangle(1.06, 0.42)
        with Locations((px - 0.28, 0.62), (px + 0.28, 0.62)):
            Rectangle(0.14, 0.34, mode=Mode.SUBTRACT)

    if profile_kind in ("shcs", "bhcs", "fhcs", "pan", "hex_bolt"):
        with Locations((px, -0.14)):
            Rectangle(0.46, 0.98)
        with Locations((px, -0.04), (px, -0.28), (px, -0.52)):
            Rectangle(0.68, 0.13)
    elif profile_kind == "wood":
        Polygon(
            (px - 0.58, 0.80),
            (px + 0.58, 0.80),
            (px + 0.22, 0.36),
            (px - 0.22, 0.36),
            align=None,
        )
        Polygon(
            (px - 0.22, 0.40),
            (px + 0.22, 0.40),
            (px, -0.80),
            align=None,
        )
        with Locations((px, 0.10)):
            Rectangle(0.68, 0.13)
        with Locations((px, -0.18)):
            Rectangle(0.54, 0.13)
        with Locations((px, -0.46)):
            Rectangle(0.40, 0.13)
    elif profile_kind == "set_screw":
        with Locations((px, 0.0)):
            Rectangle(0.58, 1.36)
        with Locations((px, 0.42), (px, 0.14), (px, -0.14), (px, -0.42)):
            Rectangle(0.84, 0.14)
        with Locations((px, 0.52)):
            Rectangle(0.32, 0.32, mode=Mode.SUBTRACT)


def _add_combo_drive(drive_kind: str) -> None:
    """
    Draw the right-side top-down drive view (at X = +0.50, Y = -0.18, R = 0.46)
    for combined Profile+Drive icons.
    """
    dx, dy = 0.50, -0.18
    dr = 0.46
    with Locations((dx, dy)):
        if drive_kind == "external_hex":
            RegularPolygon(radius=0.48, side_count=6)
            Circle(radius=0.26, mode=Mode.SUBTRACT)
            return

        Circle(radius=dr)
        if drive_kind == "hex":
            RegularPolygon(radius=0.25, side_count=6, mode=Mode.SUBTRACT)
        elif drive_kind == "torx":
            RegularPolygon(radius=0.28, side_count=3, rotation=0.0, mode=Mode.SUBTRACT)
            RegularPolygon(radius=0.28, side_count=3, rotation=60.0, mode=Mode.SUBTRACT)
        elif drive_kind == "phillips":
            Rectangle(0.56, 0.16, mode=Mode.SUBTRACT)
            Rectangle(0.16, 0.56, mode=Mode.SUBTRACT)
        elif drive_kind == "slotted":
            Rectangle(0.66, 0.18, mode=Mode.SUBTRACT)
        elif drive_kind == "square":
            Rectangle(0.34, 0.34, mode=Mode.SUBTRACT)


# ============================================================================
# MECHANICAL ICON LIBRARY — Top-Down Screw & Fastener Drives
# ============================================================================


@register_icon(
    "screw_phillips",
    category="mechanical",
    aliases=("drive_phillips", "phillips"),
    description="Top-down screw head with recessed Phillips cross drive",
)
def _icon_screw_phillips() -> None:
    Circle(radius=HEAD_R)
    Rectangle(1.05, 0.26, mode=Mode.SUBTRACT)
    Rectangle(0.26, 1.05, mode=Mode.SUBTRACT)


@register_icon(
    "drive_pozidriv",
    category="mechanical",
    aliases=("pozidriv", "pozi", "screw_pozidriv"),
    description="Top-down screw head with Pozidriv cross and 45-degree tick marks",
)
def _icon_drive_pozidriv() -> None:
    Circle(radius=HEAD_R)
    Rectangle(1.08, 0.26, mode=Mode.SUBTRACT)
    Rectangle(0.26, 1.08, mode=Mode.SUBTRACT)
    Rectangle(0.76, 0.14, rotation=45.0, mode=Mode.SUBTRACT)
    Rectangle(0.76, 0.14, rotation=-45.0, mode=Mode.SUBTRACT)


@register_icon(
    "screw_slotted",
    category="mechanical",
    aliases=("drive_slotted", "slotted", "screw_flat"),
    description="Top-down screw head with recessed straight slotted drive",
)
def _icon_screw_slotted() -> None:
    Circle(radius=HEAD_R)
    Rectangle(1.24, 0.28, mode=Mode.SUBTRACT)


@register_icon(
    "screw_hex",
    category="mechanical",
    aliases=("drive_hex", "screw_allen", "allen"),
    description="Top-down socket head with recessed internal hex (Allen) drive",
)
def _icon_screw_hex() -> None:
    Circle(radius=HEAD_R)
    RegularPolygon(radius=0.48, side_count=6, mode=Mode.SUBTRACT)


@register_icon(
    "screw_torx",
    category="mechanical",
    aliases=("drive_torx", "torx", "star_drive"),
    description="Top-down screw head with 6-point star (Torx) drive recess",
)
def _icon_screw_torx() -> None:
    Circle(radius=HEAD_R)
    RegularPolygon(radius=0.54, side_count=3, rotation=0.0, mode=Mode.SUBTRACT)
    RegularPolygon(radius=0.54, side_count=3, rotation=60.0, mode=Mode.SUBTRACT)


@register_icon(
    "screw_square",
    category="mechanical",
    aliases=("drive_square", "robertson"),
    description="Top-down screw head with recessed Robertson square drive",
)
def _icon_screw_square() -> None:
    Circle(radius=HEAD_R)
    Rectangle(0.62, 0.62, mode=Mode.SUBTRACT)


@register_icon(
    "drive_external_hex",
    category="mechanical",
    aliases=("hex_head_top", "bolt_hex_top"),
    description="Top-down external hexagon bolt head with chamfer ring indicator",
)
def _icon_drive_external_hex() -> None:
    RegularPolygon(radius=HEAD_R, side_count=6)
    Circle(radius=0.56, mode=Mode.SUBTRACT)
    Circle(radius=0.38, mode=Mode.ADD)


# ============================================================================
# MECHANICAL ICON LIBRARY — Side-Profile Fasteners
# ============================================================================


@register_icon(
    "bolt",
    category="mechanical",
    aliases=("profile_shcs", "bolt_socket", "shcs"),
    description="Socket head cap screw (DIN 912) side profile with thread ribs",
)
def _icon_bolt() -> None:
    with Locations((0.0, 0.55)):
        Rectangle(1.20, 0.50)
    _add_standard_shank_and_threads()


@register_icon(
    "bolt_hex",
    category="mechanical",
    aliases=("profile_hex_bolt", "hex_bolt"),
    description="Hex head bolt (DIN 933) side profile with wrench-flat facets",
)
def _icon_bolt_hex() -> None:
    with Locations((0.0, 0.58)):
        Rectangle(1.36, 0.44)
    with Locations((0.0, 0.36)):
        Rectangle(1.52, 0.14)
    with Locations((-0.36, 0.62), (0.36, 0.62)):
        Rectangle(0.16, 0.36, mode=Mode.SUBTRACT)
    _add_standard_shank_and_threads()


@register_icon(
    "screw_button",
    category="mechanical",
    aliases=("profile_bhcs", "bhcs", "button_head"),
    description="Domed button head cap screw (ISO 7380) side profile",
)
def _icon_screw_button() -> None:
    with Locations((0.0, 0.30)):
        Circle(radius=0.72)
    with Locations((0.0, -0.20)):
        Rectangle(1.60, 1.00, mode=Mode.SUBTRACT)
    _add_standard_shank_and_threads()


@register_icon(
    "screw_pan",
    category="mechanical",
    aliases=("profile_pan", "pan_head", "phms"),
    description="Rounded flat-top pan head machine screw (DIN 7985) side profile",
)
def _icon_screw_pan() -> None:
    with Locations((0.0, 0.50)):
        Rectangle(1.32, 0.36)
    with Locations((0.0, 0.56)):
        Rectangle(1.08, 0.38)
    _add_standard_shank_and_threads()


@register_icon(
    "screw_countersunk",
    category="mechanical",
    aliases=("profile_fhcs", "screw_flathead", "fhcs", "countersunk"),
    description="90-degree countersunk flat head screw (DIN 7991) side profile",
)
def _icon_screw_countersunk() -> None:
    Polygon((-0.78, 0.80), (0.78, 0.80), (0.28, 0.30), (-0.28, 0.30), align=None)
    _add_standard_shank_and_threads()


@register_icon(
    "screw_wood",
    category="mechanical",
    aliases=("profile_wood", "wood_screw", "sheet_metal_screw", "self_tapping"),
    description="Tapered self-tapping / wood screw side profile with pointed tip",
)
def _icon_screw_wood() -> None:
    Polygon((-0.76, 0.82), (0.76, 0.82), (0.28, 0.36), (-0.28, 0.36), align=None)
    Polygon((-0.28, 0.40), (0.28, 0.40), (0.0, -0.82), align=None)
    with Locations((0.0, 0.10)):
        Rectangle(0.84, RIB_H)
    with Locations((0.0, -0.18)):
        Rectangle(0.68, RIB_H)
    with Locations((0.0, -0.46)):
        Rectangle(0.50, RIB_H)


@register_icon(
    "set_screw",
    category="mechanical",
    aliases=("profile_set_screw", "grub_screw"),
    description="Headless threaded grub / set screw side profile with top socket",
)
def _icon_set_screw() -> None:
    Rectangle(0.76, 1.48)
    with Locations((0.0, 0.45), (0.0, 0.15), (0.0, -0.15), (0.0, -0.45)):
        Rectangle(1.12, 0.16)
    with Locations((0.0, 0.58)):
        Rectangle(0.42, 0.36, mode=Mode.SUBTRACT)


# ============================================================================
# MECHANICAL ICON LIBRARY — Combined Profile + Drive Fastener Views
# ============================================================================


@register_icon(
    "shcs_hex",
    category="mechanical",
    aliases=("bolt_allen", "shcs_allen", "bolt_hex_drive"),
    description="Socket head cap screw (SHCS) side profile + internal hex drive",
)
def _icon_shcs_hex() -> None:
    _add_combo_profile("shcs")
    _add_combo_drive("hex")


@register_icon(
    "shcs_torx",
    category="mechanical",
    aliases=("bolt_torx",),
    description="Socket head cap screw (SHCS) side profile + 6-lobe Torx drive",
)
def _icon_shcs_torx() -> None:
    _add_combo_profile("shcs")
    _add_combo_drive("torx")


@register_icon(
    "bhcs_hex",
    category="mechanical",
    aliases=("button_hex", "bhcs_allen"),
    description="Button head cap screw (BHCS) side profile + internal hex drive",
)
def _icon_bhcs_hex() -> None:
    _add_combo_profile("bhcs")
    _add_combo_drive("hex")


@register_icon(
    "bhcs_torx",
    category="mechanical",
    aliases=("button_torx",),
    description="Button head cap screw (BHCS) side profile + 6-lobe Torx drive",
)
def _icon_bhcs_torx() -> None:
    _add_combo_profile("bhcs")
    _add_combo_drive("torx")


@register_icon(
    "bhcs_phillips",
    category="mechanical",
    aliases=("button_phillips",),
    description="Button head screw side profile + Phillips cross drive",
)
def _icon_bhcs_phillips() -> None:
    _add_combo_profile("bhcs")
    _add_combo_drive("phillips")


@register_icon(
    "fhcs_hex",
    category="mechanical",
    aliases=("countersunk_hex", "fhcs_allen", "flathead_hex"),
    description="Countersunk flat head (FHCS) side profile + internal hex drive",
)
def _icon_fhcs_hex() -> None:
    _add_combo_profile("fhcs")
    _add_combo_drive("hex")


@register_icon(
    "fhcs_torx",
    category="mechanical",
    aliases=("countersunk_torx", "flathead_torx"),
    description="Countersunk flat head (FHCS) side profile + 6-lobe Torx drive",
)
def _icon_fhcs_torx() -> None:
    _add_combo_profile("fhcs")
    _add_combo_drive("torx")


@register_icon(
    "fhcs_phillips",
    category="mechanical",
    aliases=("countersunk_phillips", "flathead_phillips"),
    description="Countersunk flat head (FHCS) side profile + Phillips cross drive",
)
def _icon_fhcs_phillips() -> None:
    _add_combo_profile("fhcs")
    _add_combo_drive("phillips")


@register_icon(
    "fhcs_slotted",
    category="mechanical",
    aliases=("countersunk_slotted", "flathead_slotted"),
    description="Countersunk flat head (FHCS) side profile + straight slotted drive",
)
def _icon_fhcs_slotted() -> None:
    _add_combo_profile("fhcs")
    _add_combo_drive("slotted")


@register_icon(
    "pan_phillips",
    category="mechanical",
    aliases=("phms_phillips", "pan_head_phillips"),
    description="Pan head machine screw side profile + Phillips cross drive",
)
def _icon_pan_phillips() -> None:
    _add_combo_profile("pan")
    _add_combo_drive("phillips")


@register_icon(
    "pan_torx",
    category="mechanical",
    aliases=("phms_torx", "pan_head_torx"),
    description="Pan head machine screw side profile + 6-lobe Torx drive",
)
def _icon_pan_torx() -> None:
    _add_combo_profile("pan")
    _add_combo_drive("torx")


@register_icon(
    "pan_slotted",
    category="mechanical",
    aliases=("phms_slotted", "pan_head_slotted"),
    description="Pan head machine screw side profile + straight slotted drive",
)
def _icon_pan_slotted() -> None:
    _add_combo_profile("pan")
    _add_combo_drive("slotted")


@register_icon(
    "hex_bolt_combo",
    category="mechanical",
    aliases=("bolt_hex_combo", "hex_cap_combo"),
    description="Hex head bolt side profile + top-down external hex wrench head",
)
def _icon_hex_bolt_combo() -> None:
    _add_combo_profile("hex_bolt")
    _add_combo_drive("external_hex")


@register_icon(
    "wood_phillips",
    category="mechanical",
    aliases=("wood_screw_phillips",),
    description="Tapered wood/sheet-metal screw side profile + Phillips drive",
)
def _icon_wood_phillips() -> None:
    _add_combo_profile("wood")
    _add_combo_drive("phillips")


@register_icon(
    "wood_torx",
    category="mechanical",
    aliases=("wood_screw_torx", "construction_screw"),
    description="Tapered wood/construction screw side profile + Torx star drive",
)
def _icon_wood_torx() -> None:
    _add_combo_profile("wood")
    _add_combo_drive("torx")


@register_icon(
    "wood_square",
    category="mechanical",
    aliases=("wood_screw_square", "deck_screw", "pocket_screw"),
    description="Tapered wood/deck screw side profile + Robertson square drive",
)
def _icon_wood_square() -> None:
    _add_combo_profile("wood")
    _add_combo_drive("square")


@register_icon(
    "set_screw_hex",
    category="mechanical",
    aliases=("grub_hex", "grub_screw_hex"),
    description="Headless set/grub screw side profile + internal hex socket drive",
)
def _icon_set_screw_hex() -> None:
    _add_combo_profile("set_screw")
    _add_combo_drive("hex")


# ============================================================================
# MECHANICAL ICON LIBRARY — Nuts, Washers & Inserts (Both Profile & Top Views)
# ============================================================================


@register_icon(
    "nut",
    category="mechanical",
    aliases=("nut_top", "hex_nut"),
    description="Top-down standard hexagon nut (DIN 934) with center bore",
)
def _icon_nut() -> None:
    RegularPolygon(radius=HEAD_R, side_count=6)
    Circle(radius=0.45, mode=Mode.SUBTRACT)


@register_icon(
    "nut_profile",
    category="mechanical",
    aliases=("hex_nut_profile",),
    description="Side-profile standard hex nut (DIN 934) with wrench-flat facets",
)
def _icon_nut_profile() -> None:
    Rectangle(1.68, 0.84)
    with Locations((-0.44, 0.0), (0.44, 0.0)):
        Rectangle(0.18, 0.60, mode=Mode.SUBTRACT)


@register_icon(
    "nut_lock",
    category="mechanical",
    aliases=("nyloc", "lock_nut", "nut_lock_profile"),
    description="Side-profile nylon-insert hex lock nut (DIN 985) with domed collar",
)
def _icon_nut_lock() -> None:
    with Locations((0.0, -0.22)):
        Rectangle(1.64, 0.72)
    with Locations((0.0, 0.24)):
        Rectangle(1.16, 0.48)
    with Locations((-0.44, -0.22), (0.44, -0.22)):
        Rectangle(0.18, 0.52, mode=Mode.SUBTRACT)
    with Locations((0.0, 0.32)):
        Rectangle(0.46, 0.36, mode=Mode.SUBTRACT)


@register_icon(
    "nut_lock_top",
    category="mechanical",
    aliases=("nyloc_top", "lock_nut_top"),
    description="Top-down hex lock nut (DIN 985) with concentric nylon insert ring",
)
def _icon_nut_lock_top() -> None:
    RegularPolygon(radius=HEAD_R, side_count=6)
    Circle(radius=0.58, mode=Mode.SUBTRACT)
    Circle(radius=0.44, mode=Mode.ADD)
    Circle(radius=0.26, mode=Mode.SUBTRACT)


@register_icon(
    "nut_flange",
    category="mechanical",
    aliases=("flange_nut", "nut_flange_profile"),
    description="Side-profile hex flange nut (DIN 6923) with wide integrated base",
)
def _icon_nut_flange() -> None:
    with Locations((0.0, -0.38)):
        Rectangle(1.76, 0.28)
    with Locations((0.0, 0.12)):
        Rectangle(1.28, 0.76)
    with Locations((-0.36, 0.14), (0.36, 0.14)):
        Rectangle(0.18, 0.54, mode=Mode.SUBTRACT)


@register_icon(
    "nut_flange_top",
    category="mechanical",
    aliases=("flange_nut_top",),
    description="Top-down hex flange nut showing outer flange ring and hex flats",
)
def _icon_nut_flange_top() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.72, mode=Mode.SUBTRACT)
    RegularPolygon(radius=0.62, side_count=6, mode=Mode.ADD)
    Circle(radius=0.30, mode=Mode.SUBTRACT)


@register_icon(
    "nut_tnut",
    category="mechanical",
    aliases=("tnut", "hammer_nut", "nut_tnut_profile"),
    description="Side/cross-section profile of aluminum extrusion T-slot nut",
)
def _icon_nut_tnut() -> None:
    with Locations((0.0, 0.10)):
        Rectangle(1.72, 0.42)
    with Locations((0.0, 0.44)):
        Rectangle(0.92, 0.36)
    Polygon((-0.86, -0.10), (0.86, -0.10), (0.54, -0.48), (-0.54, -0.48), align=None)
    with Locations((0.0, 0.22)):
        Rectangle(0.36, 0.84, mode=Mode.SUBTRACT)


@register_icon(
    "nut_tnut_top",
    category="mechanical",
    aliases=("tnut_top", "hammer_nut_top"),
    description="Top-down drop-in hammer T-nut with relieved cam corners and bore",
)
def _icon_nut_tnut_top() -> None:
    Polygon(
        (-0.84, 0.52),
        (0.42, 0.52),
        (0.84, 0.10),
        (0.84, -0.52),
        (-0.42, -0.52),
        (-0.84, -0.10),
        align=None,
    )
    Circle(radius=0.30, mode=Mode.SUBTRACT)


@register_icon(
    "insert_heatset",
    category="mechanical",
    aliases=("heatset", "threaded_insert", "insert_heatset_profile"),
    description="Side-profile knurled brass heat-set threaded insert with knurl bands",
)
def _icon_insert_heatset() -> None:
    Rectangle(0.96, 1.56)
    with Locations((0.0, 0.40), (0.0, -0.14)):
        Rectangle(1.36, 0.38)
    with Locations((0.0, 0.24)):
        Rectangle(0.42, 1.12, mode=Mode.SUBTRACT)


@register_icon(
    "insert_heatset_top",
    category="mechanical",
    aliases=("heatset_top", "threaded_insert_top"),
    description="Top-down knurled brass heat-set insert ring with external splines",
)
def _icon_insert_heatset_top() -> None:
    Circle(radius=0.78)
    for angle in (0.0, 30.0, 60.0, 90.0, 120.0, 150.0):
        Rectangle(1.80, 0.24, rotation=angle)
    Circle(radius=0.48, mode=Mode.SUBTRACT)


@register_icon(
    "washer",
    category="mechanical",
    aliases=("flat_washer", "washer_top"),
    description="Top-down standard flat washer (DIN 125) ring",
)
def _icon_washer() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.42, mode=Mode.SUBTRACT)


@register_icon(
    "washer_profile",
    category="mechanical",
    aliases=("flat_washer_profile",),
    description="Side-profile flat washer plate showing thickness and center bore",
)
def _icon_washer_profile() -> None:
    Rectangle(1.76, 0.44)
    Rectangle(0.56, 0.20, mode=Mode.SUBTRACT)


@register_icon(
    "washer_split",
    category="mechanical",
    aliases=("lock_washer", "split_washer"),
    description="Top-down helical split-ring lock washer (DIN 127) with angled gap",
)
def _icon_washer_split() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.42, mode=Mode.SUBTRACT)
    with Locations((0.0, 0.64)):
        Rectangle(0.28, 0.72, rotation=20.0, mode=Mode.SUBTRACT)


@register_icon(
    "washer_fender",
    category="mechanical",
    aliases=("fender_washer", "penny_washer"),
    description="Top-down large-OD, small-ID fender washer (DIN 9021)",
)
def _icon_washer_fender() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.25, mode=Mode.SUBTRACT)


@register_icon(
    "washer_star",
    category="mechanical",
    aliases=(
        "star_washer",
        "tooth_washer",
        "washer_star_external",
        "external_star_washer",
    ),
    description="Top-down external-tooth star lock washer (DIN 6797A)",
)
def _icon_washer_star() -> None:
    Circle(radius=0.68)
    for angle in (0.0, 22.5, 45.0, 67.5, 90.0, 112.5, 135.0, 157.5):
        Rectangle(1.80, 0.22, rotation=angle)
    Circle(radius=0.38, mode=Mode.SUBTRACT)


@register_icon(
    "washer_star_internal",
    category="mechanical",
    aliases=("internal_star_washer", "internal_tooth_washer"),
    description="Top-down internal-tooth star lock washer (DIN 6797J)",
)
def _icon_washer_star_internal() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.62, mode=Mode.SUBTRACT)
    for angle in (0.0, 45.0, 90.0, 135.0):
        Rectangle(1.40, 0.22, rotation=angle, mode=Mode.ADD)
    Circle(radius=0.30, mode=Mode.SUBTRACT)


@register_icon(
    "washer_star_profile",
    category="mechanical",
    aliases=("star_washer_profile", "tooth_washer_profile"),
    description="Side-profile serrated tooth star lock washer",
)
def _icon_washer_star_profile() -> None:
    Rectangle(1.76, 0.28)
    for x_pos in (-0.64, -0.22, 0.22, 0.64):
        with Locations((x_pos, 0.0)):
            Rectangle(0.22, 0.56, rotation=24.0)


# ============================================================================
# MECHANICAL ICON LIBRARY — Pins, Stand-Offs, Motion & Structural Hardware
# ============================================================================


@register_icon(
    "standoff",
    category="mechanical",
    aliases=("hex_standoff", "spacer", "standoff_profile"),
    description="Side-profile male-female hex standoff with top stud and bottom bore",
)
def _icon_standoff() -> None:
    with Locations((0.0, -0.16)):
        Rectangle(0.98, 1.16)
    with Locations((0.0, 0.64)):
        Rectangle(0.46, 0.52)
    with Locations((0.0, -0.52)):
        Rectangle(0.44, 0.46, mode=Mode.SUBTRACT)


@register_icon(
    "standoff_top",
    category="mechanical",
    aliases=("spacer_top", "hex_standoff_top"),
    description="Top-down hex standoff / threaded spacer with small internal thread bore",
)
def _icon_standoff_top() -> None:
    RegularPolygon(radius=HEAD_R, side_count=6)
    Circle(radius=0.30, mode=Mode.SUBTRACT)


@register_icon(
    "dowel_pin",
    category="mechanical",
    aliases=("pin", "shaft"),
    description="Precision cylindrical dowel pin with chamfered ends",
)
def _icon_dowel_pin() -> None:
    Polygon(
        (-0.24, 0.86),
        (0.24, 0.86),
        (0.38, 0.68),
        (0.38, -0.68),
        (0.24, -0.86),
        (-0.24, -0.86),
        (-0.38, -0.68),
        (-0.38, 0.68),
        align=None,
    )


@register_icon(
    "retaining_ring",
    category="mechanical",
    aliases=("circlip", "e_clip", "c_clip"),
    description="External C-clip / circlip retaining ring with installation lugs",
)
def _icon_retaining_ring() -> None:
    Circle(radius=HEAD_R)
    with Locations((0.0, -0.08)):
        Circle(radius=0.52, mode=Mode.SUBTRACT)
    with Locations((0.0, -0.68)):
        Rectangle(0.56, 0.60, mode=Mode.SUBTRACT)
    with Locations((-0.34, -0.52), (0.34, -0.52)):
        Rectangle(0.26, 0.28, mode=Mode.ADD)


@register_icon(
    "rivet",
    category="mechanical",
    aliases=("pop_rivet", "blind_rivet"),
    description="Domed blind pop rivet side profile with mandrel stem",
)
def _icon_rivet() -> None:
    with Locations((0.0, 0.14)):
        Circle(radius=0.68)
    with Locations((0.0, -0.36)):
        Rectangle(1.50, 1.00, mode=Mode.SUBTRACT)
    with Locations((0.0, 0.52)):
        Rectangle(0.68, 0.68)
    with Locations((0.0, -0.30)):
        Rectangle(0.28, 0.96)


@register_icon(
    "spring",
    category="mechanical",
    aliases=("coil_spring",),
    description="Helical compression spring with connected rounded-path coil nodes",
)
def _icon_spring() -> None:
    _add_rounded_polyline(
        [
            (-0.54, 0.78),
            (0.54, 0.78),
            (-0.54, 0.26),
            (0.54, -0.26),
            (-0.54, -0.78),
            (0.54, -0.78),
        ],
        stroke_w=STROKE_W,
    )


@register_icon(
    "bearing",
    category="mechanical",
    aliases=("ball_bearing",),
    description="Deep-groove radial ball bearing with inner and outer races",
)
def _icon_bearing() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.58, mode=Mode.SUBTRACT)
    Circle(radius=0.40, mode=Mode.ADD)
    Circle(radius=0.18, mode=Mode.SUBTRACT)


@register_icon(
    "oring",
    category="mechanical",
    aliases=("gasket", "seal"),
    description="Elastomeric O-ring seal with narrow torus cross-section",
)
def _icon_oring() -> None:
    Circle(radius=HEAD_R)
    Circle(radius=0.62, mode=Mode.SUBTRACT)


@register_icon(
    "gear",
    category="mechanical",
    aliases=("spur_gear", "cog"),
    description="8-tooth involute spur gear with center shaft bore",
)
def _icon_gear() -> None:
    Circle(radius=0.66)
    for angle in (0.0, 45.0, 90.0, 135.0):
        Rectangle(1.80, 0.34, rotation=angle)
    Circle(radius=0.30, mode=Mode.SUBTRACT)


@register_icon(
    "pulley",
    category="mechanical",
    aliases=("timing_pulley", "gt2"),
    description="Toothed GT2 timing belt pulley wheel with hub and bore",
)
def _icon_pulley() -> None:
    Circle(radius=0.76)
    for angle in (0.0, 30.0, 60.0, 90.0, 120.0, 150.0):
        Rectangle(1.80, 0.22, rotation=angle)
    Circle(radius=0.50, mode=Mode.SUBTRACT)
    Circle(radius=0.32, mode=Mode.ADD)


@register_icon(
    "extrusion",
    category="mechanical",
    aliases=("vslot", "tslot", "2020"),
    description="2020 V-slot / T-slot structural aluminum extrusion profile",
)
def _icon_extrusion() -> None:
    Rectangle(1.68, 1.68)
    for angle in (0.0, 90.0):
        Rectangle(1.80, 0.36, rotation=angle, mode=Mode.SUBTRACT)
    with Locations((0.52, 0.0), (-0.52, 0.0)):
        Rectangle(0.32, 0.76, mode=Mode.SUBTRACT)
    with Locations((0.0, 0.52), (0.0, -0.52)):
        Rectangle(0.76, 0.32, mode=Mode.SUBTRACT)
    Rectangle(0.68, 0.68, mode=Mode.ADD)
    Circle(radius=0.22, mode=Mode.SUBTRACT)


@register_icon(
    "magnet",
    category="mechanical",
    aliases=("neodymium",),
    description="Horseshoe U-magnet profile with dual poles",
)
def _icon_magnet() -> None:
    with Locations((0.0, -0.08)):
        Circle(radius=0.78)
    with Locations((0.0, 0.34)):
        Rectangle(1.56, 0.84)
    with Locations((0.0, -0.08)):
        Circle(radius=0.32, mode=Mode.SUBTRACT)
    with Locations((0.0, 0.36)):
        Rectangle(0.64, 0.92, mode=Mode.SUBTRACT)


# ============================================================================
# ELECTRICAL ICON LIBRARY — Passives (Schematic Style)
# ============================================================================


@register_icon(
    "resistor",
    category="electrical",
    aliases=("res",),
    description="Axial resistor schematic symbol with rectangular body and leads",
)
def _icon_resistor() -> None:
    Rectangle(LEAD_SPAN, STROKE_W)
    Rectangle(1.05, 0.68, mode=Mode.ADD)


@register_icon(
    "potentiometer",
    category="electrical",
    aliases=("trimmer", "pot", "rheostat"),
    description="Variable resistor / potentiometer with diagonal wiper arrow",
)
def _icon_potentiometer() -> None:
    Rectangle(LEAD_SPAN, STROKE_W)
    Rectangle(0.96, 0.56, mode=Mode.ADD)
    Rectangle(0.20, 1.44, rotation=-35.0, mode=Mode.ADD)
    with Locations((0.38, 0.54)):
        RegularPolygon(radius=0.28, side_count=3, rotation=55.0, mode=Mode.ADD)


@register_icon(
    "capacitor",
    category="electrical",
    aliases=("cap", "ceramic_cap"),
    description="Non-polarized parallel-plate capacitor symbol with axial leads",
)
def _icon_capacitor() -> None:
    with Locations((-0.55, 0.0), (0.55, 0.0)):
        Rectangle(0.70, STROKE_W)
    with Locations((-0.24, 0.0), (0.24, 0.0)):
        Rectangle(0.26, 1.44)


@register_icon(
    "capacitor_electrolytic",
    category="electrical",
    aliases=("electrolytic", "elcap"),
    description="Polarized electrolytic capacitor with anode plate and '+' mark",
)
def _icon_capacitor_electrolytic() -> None:
    with Locations((-0.55, 0.0), (0.55, 0.0)):
        Rectangle(0.70, STROKE_W)
    with Locations((-0.22, 0.0)):
        Rectangle(0.26, 1.44)
    with Locations((0.26, 0.0)):
        Rectangle(0.24, 1.44)
    with Locations((0.40, 0.60), (0.40, -0.60)):
        Rectangle(0.32, 0.24)
    with Locations((-0.62, 0.54)):
        Rectangle(0.42, 0.16)
        Rectangle(0.16, 0.42)


@register_icon(
    "inductor",
    category="electrical",
    aliases=("coil", "choke", "ferrite"),
    description="3-arch magnetic inductor / choke coil with axial leads",
)
def _icon_inductor() -> None:
    with Locations((-0.46, -0.10), (0.0, -0.10), (0.46, -0.10)):
        Circle(radius=0.30)
    with Locations((0.0, -0.45)):
        Rectangle(1.80, 0.60, mode=Mode.SUBTRACT)
    with Locations((0.0, -0.18)):
        Rectangle(LEAD_SPAN, STROKE_W, mode=Mode.ADD)


@register_icon(
    "fuse",
    category="electrical",
    aliases=("ptc", "polyfuse"),
    description="IEC fuse symbol with cartridge outline and continuous center element",
)
def _icon_fuse() -> None:
    Rectangle(1.16, 0.78)
    Rectangle(0.74, 0.40, mode=Mode.SUBTRACT)
    Rectangle(LEAD_SPAN, STROKE_W, mode=Mode.ADD)


@register_icon(
    "crystal",
    category="electrical",
    aliases=("oscillator", "xtal"),
    description="Quartz crystal resonator slab between excitation plates",
)
def _icon_crystal() -> None:
    Rectangle(0.32, 1.38)
    with Locations((-0.42, 0.0), (0.42, 0.0)):
        Rectangle(0.20, 1.02)
    with Locations((-0.66, 0.0), (0.66, 0.0)):
        Rectangle(0.48, STROKE_W)


# ============================================================================
# ELECTRICAL ICON LIBRARY — Semiconductors (Schematic + Package Hybrid)
# ============================================================================


@register_icon(
    "diode",
    category="electrical",
    aliases=("rectifier",),
    description="Semiconductor diode symbol with leads and cathode bar",
)
def _icon_diode() -> None:
    Rectangle(LEAD_SPAN, 0.20)
    with Locations((-0.10, 0.0)):
        RegularPolygon(radius=0.55, side_count=3, rotation=0.0, mode=Mode.ADD)
    with Locations((0.42, 0.0)):
        Rectangle(0.20, 0.95, mode=Mode.ADD)


@register_icon(
    "zener",
    category="electrical",
    aliases=("tvs", "schottky"),
    description="Zener / TVS clamp diode symbol with winged cathode bar",
)
def _icon_zener() -> None:
    _icon_diode()
    with Locations((0.26, 0.44)):
        Rectangle(0.36, 0.18, mode=Mode.ADD)
    with Locations((0.58, -0.44)):
        Rectangle(0.36, 0.18, mode=Mode.ADD)


@register_icon(
    "led",
    category="electrical",
    aliases=("photodiode", "opto"),
    description="Light-emitting diode (LED) symbol with dual outward photon rays",
)
def _icon_led() -> None:
    with Locations((0.0, -0.22)):
        Rectangle(LEAD_SPAN, 0.20)
    with Locations((-0.12, -0.22)):
        RegularPolygon(radius=0.50, side_count=3, rotation=0.0, mode=Mode.ADD)
    with Locations((0.36, -0.22)):
        Rectangle(0.20, 0.86, mode=Mode.ADD)
    with Locations((-0.16, 0.48), (0.24, 0.48)):
        Rectangle(0.52, 0.16, rotation=45.0, mode=Mode.ADD)


@register_icon(
    "transistor",
    category="electrical",
    aliases=("bjt", "npn", "pnp"),
    description="Bipolar junction transistor (BJT) schematic symbol (B/C/E)",
)
def _icon_transistor() -> None:
    with Locations((-0.56, 0.0)):
        Rectangle(0.68, STROKE_W)
    with Locations((-0.18, 0.0)):
        Rectangle(0.24, 1.16)
    with Locations((0.18, 0.36)):
        Rectangle(0.84, 0.20, rotation=32.0)
    with Locations((0.18, -0.36)):
        Rectangle(0.84, 0.20, rotation=-32.0)
    with Locations((0.48, 0.68), (0.48, -0.68)):
        Rectangle(0.22, 0.42)


@register_icon(
    "mosfet",
    category="electrical",
    aliases=("fet", "power_fet", "to220"),
    description="TO-220 power MOSFET / voltage regulator package with heatsink tab",
)
def _icon_mosfet() -> None:
    with Locations((0.0, 0.02)):
        Rectangle(1.28, 0.78)
    with Locations((0.0, 0.58)):
        Rectangle(1.28, 0.48)
    with Locations((0.0, 0.58)):
        Circle(radius=0.20, mode=Mode.SUBTRACT)
    with Locations((-0.44, -0.60), (0.0, -0.60), (0.44, -0.60)):
        Rectangle(0.20, 0.58, mode=Mode.ADD)


# ============================================================================
# ELECTRICAL ICON LIBRARY — Packages, Interconnects, Electromechanical & Power
# ============================================================================


@register_icon(
    "ic",
    category="electrical",
    aliases=("chip", "dip", "mcu", "opamp"),
    description="Dual-in-line (DIP/SOIC) integrated circuit package with index notch",
)
def _icon_ic() -> None:
    Rectangle(0.96, 1.56)
    with Locations((0.0, 0.78)):
        Circle(radius=0.22, mode=Mode.SUBTRACT)
    for y_pos in (-0.52, -0.18, 0.18, 0.52):
        with Locations((0.0, y_pos)):
            Rectangle(1.68, 0.18, mode=Mode.ADD)


@register_icon(
    "switch",
    category="electrical",
    aliases=("spst", "toggle"),
    description="Single-pole (SPST) open blade switch with contact terminals",
)
def _icon_switch() -> None:
    with Locations((-0.66, -0.18), (0.66, -0.18)):
        Rectangle(0.48, STROKE_W)
    with Locations((-0.42, -0.18), (0.42, -0.18)):
        Circle(radius=0.20)
    with Locations((-0.04, 0.08)):
        Rectangle(0.96, 0.20, rotation=28.0)


@register_icon(
    "pushbutton",
    category="electrical",
    aliases=("tactile_switch", "button"),
    description="Momentary tactile push-button switch profile with plunger and pins",
)
def _icon_pushbutton() -> None:
    with Locations((0.0, -0.10)):
        Rectangle(1.44, 0.56)
    with Locations((0.0, 0.36)):
        Rectangle(0.72, 0.46)
    with Locations((-0.48, -0.54), (0.48, -0.54)):
        Rectangle(0.22, 0.44)
    with Locations((0.0, -0.10)):
        Rectangle(1.80, 0.20)


@register_icon(
    "connector",
    category="electrical",
    aliases=("header", "jst", "dupont", "plug"),
    description="Shrouded 4-pin header / JST board connector housing with pins",
)
def _icon_connector() -> None:
    with Locations((0.0, 0.22)):
        Rectangle(1.68, 1.04)
    with Locations((0.0, 0.32)):
        Rectangle(1.24, 0.56, mode=Mode.SUBTRACT)
    for x_pos in (-0.45, -0.15, 0.15, 0.45):
        with Locations((x_pos, -0.16)):
            Rectangle(0.16, 1.12, mode=Mode.ADD)


@register_icon(
    "terminal",
    category="electrical",
    aliases=("crimp", "ring_terminal", "lug"),
    description="Crimp ring terminal lug with eyelet and insulated barrel",
)
def _icon_terminal() -> None:
    with Locations((0.0, 0.28)):
        Circle(radius=0.60)
    with Locations((0.0, -0.38)):
        Rectangle(0.68, 0.96)
    with Locations((0.0, 0.28)):
        Circle(radius=0.26, mode=Mode.SUBTRACT)


@register_icon(
    "wire",
    category="electrical",
    aliases=("cable", "jumper", "hookup"),
    description="Insulated hookup wire jacket with stripped multi-strand conductor",
)
def _icon_wire() -> None:
    with Locations((-0.38, 0.0)):
        Rectangle(1.04, 0.68)
    with Locations((0.36, 0.0)):
        Rectangle(0.84, 0.18)
    with Locations((0.34, 0.22)):
        Rectangle(0.80, 0.16, rotation=22.0)
    with Locations((0.34, -0.22)):
        Rectangle(0.80, 0.16, rotation=-22.0)


@register_icon(
    "battery",
    category="electrical",
    aliases=("cell", "lipo", "power"),
    description="Multi-cell DC battery source symbol with alternating long/short plates",
)
def _icon_battery() -> None:
    with Locations((-0.68, 0.0), (0.68, 0.0)):
        Rectangle(0.44, STROKE_W)
    with Locations((-0.42, 0.0), (0.14, 0.0)):
        Rectangle(0.20, 1.48)
    with Locations((-0.14, 0.0), (0.42, 0.0)):
        Rectangle(0.24, 0.78)


@register_icon(
    "ground",
    category="electrical",
    aliases=("gnd", "earth"),
    description="Standard 3-tier earth / chassis ground schematic symbol",
)
def _icon_ground() -> None:
    with Locations((0.0, 0.38)):
        Rectangle(STROKE_W, 0.86)
    with Locations((0.0, -0.02)):
        Rectangle(1.64, 0.24)
    with Locations((0.0, -0.38)):
        Rectangle(1.12, 0.24)
    with Locations((0.0, -0.74)):
        Rectangle(0.60, 0.24)


@register_icon(
    "motor",
    category="electrical",
    aliases=("stepper", "servo", "dc_motor"),
    description="Flanged electric motor housing with rotor pilot ring and shaft",
)
def _icon_motor() -> None:
    Circle(radius=0.78)
    Rectangle(1.76, 0.44)
    Circle(radius=0.46, mode=Mode.SUBTRACT)
    Circle(radius=0.24, mode=Mode.ADD)


# ============================================================================
# SAFETY & HAZARD ICON LIBRARY
# ============================================================================


@register_icon(
    "warning",
    category="safety",
    aliases=("hazard", "caution"),
    description="Hazard triangle with 0.4 mm nozzle-safe exclamation mark",
)
def _icon_warning() -> None:
    Triangle(a=1.8, b=1.8, c=1.8, align=(Align.CENTER, Align.CENTER))
    Triangle(
        a=1.2,
        b=1.2,
        c=1.2,
        align=(Align.CENTER, Align.CENTER),
        mode=Mode.SUBTRACT,
    )
    with Locations((0.0, 0.06)):
        Rectangle(0.22, 0.45, mode=Mode.ADD)
    with Locations((0.0, -0.34)):
        Circle(radius=0.12, mode=Mode.ADD)


@register_icon(
    "high_voltage",
    category="safety",
    aliases=("lightning", "hv", "esd"),
    description="High-voltage / ESD lightning bolt hazard symbol",
)
def _icon_high_voltage() -> None:
    Polygon(
        (0.18, 0.90),
        (-0.52, -0.04),
        (0.04, -0.04),
        (-0.22, -0.90),
        (0.52, 0.08),
        (-0.04, 0.08),
        align=None,
    )


# ============================================================================
# External SVG Resolution, Composite Pairing & Catalog Export
# ============================================================================


def resolve_procedural_icon_key(name: str) -> Optional[str]:
    """Resolve a canonical procedural icon name or alias, or None if not registered."""
    norm = name.strip().lower()
    if norm in PROCEDURAL_ICON_REGISTRY:
        return norm
    if norm in ICON_ALIASES:
        return ICON_ALIASES[norm]
    return None


def resolve_svg_icon_path(
    name: str, icons_dir: str | Path = DEFAULT_ICONS_DIR
) -> Optional[Path]:
    """Locate an external .svg icon by file path or by stem inside `icons_dir`."""
    clean = name.strip()
    if not clean or clean.lower() == "none":
        return None

    direct = Path(clean)
    if direct.suffix.lower() == ".svg" and direct.is_file():
        return direct.resolve()

    folder = Path(icons_dir)
    if direct.suffix.lower() == ".svg":
        candidate = folder / direct.name
        if candidate.is_file():
            return candidate.resolve()
    else:
        candidate = folder / f"{clean}.svg"
        if candidate.is_file():
            return candidate.resolve()
        if folder.is_dir():
            for svg_path in folder.glob("*.svg"):
                if svg_path.stem.lower() == clean.lower():
                    return svg_path.resolve()

    return None


def _load_svg_sketch(svg_path: Path) -> Optional[Sketch]:
    """Import a 2D .svg file via build123d.import_svg and normalize to a unit Sketch."""
    shapes = import_svg(str(svg_path))
    faces: list[Face] = []
    for item in shapes:
        if isinstance(item, Face):
            faces.append(item)
        elif isinstance(item, Wire) and item.is_closed:
            faces.append(Face(item))
        else:
            faces.extend(item.faces())

    if not faces:
        return None

    raw = Sketch(children=faces)
    return _center_and_normalize_sketch(raw)


def _compose_side_by_side_icons(
    left_name: str, right_name: str, icons_dir: str = str(DEFAULT_ICONS_DIR)
) -> Optional[Sketch]:
    """
    Combine any two icons side-by-side (e.g. `bolt+screw_hex` or `nut_lock+nut_lock_top`)
    into a unified centered & normalized unit Sketch.
    """
    left_sk = get_unit_icon(left_name, icons_dir)
    right_sk = get_unit_icon(right_name, icons_dir)
    if left_sk is None or right_sk is None:
        return left_sk or right_sk

    l_bb = left_sk.bounding_box()
    r_bb = right_sk.bounding_box()
    gap = 0.14
    left_moved = left_sk.moved(Location((-(l_bb.size.X / 2.0 + gap / 2.0), 0.0, 0.0)))
    right_moved = right_sk.moved(Location((+(r_bb.size.X / 2.0 + gap / 2.0), 0.0, 0.0)))
    combined = Sketch(children=list(left_moved.faces()) + list(right_moved.faces()))
    return _center_and_normalize_sketch(combined)


@lru_cache(maxsize=256)
def get_unit_icon(
    name: str, icons_dir: str = str(DEFAULT_ICONS_DIR)
) -> Optional[Sketch]:
    """
    Return a unit-normalized (max span = 1.0) Sketch centered at (0, 0)
    from the procedural library, a composite `left+right` pair, or an external .svg file.
    """
    if not name:
        return None
    norm = name.strip().lower()
    if not norm or norm == "none":
        return None

    # 0. Support dynamic `profile+drive` composite pairing (e.g. "screw_button+torx")
    if "+" in norm:
        parts = [p.strip() for p in norm.split("+", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return _compose_side_by_side_icons(parts[0], parts[1], icons_dir)

    # 1. Check Procedural Icon Registry & Aliases first (unless an explicit .svg path is given)
    if not norm.endswith(".svg"):
        proc_key = resolve_procedural_icon_key(norm)
        if proc_key is not None:
            with BuildSketch() as icon_sk:
                PROCEDURAL_ICON_REGISTRY[proc_key]()
            return _center_and_normalize_sketch(icon_sk.sketch)

    # 2. Check External .svg Icon File
    svg_path = resolve_svg_icon_path(name, icons_dir=icons_dir)
    if svg_path is not None:
        return _load_svg_sketch(svg_path)

    return None


def list_available_icons(
    icons_dir: str | Path = DEFAULT_ICONS_DIR,
) -> dict[str, list[str]]:
    """Return all registered procedural icons and external .svg icons."""
    procedural = sorted(PROCEDURAL_ICON_REGISTRY.keys())
    folder = Path(icons_dir)
    svg_icons = (
        sorted(
            p.stem.lower()
            for p in folder.glob("*.svg")
            if p.stem.lower() != "icon_catalog"
        )
        if folder.is_dir()
        else []
    )
    return {
        "procedural": procedural,
        "svg": svg_icons,
    }


def is_valid_icon(name: str, icons_dir: str | Path = DEFAULT_ICONS_DIR) -> bool:
    """Return True if `name` is 'none', a procedural icon/alias, a `left+right` pair, or an .svg file."""
    if not name or name.strip().lower() == "none":
        return True
    norm = name.strip().lower()
    if "+" in norm:
        parts = [p.strip() for p in norm.split("+", 1)]
        return (
            len(parts) == 2
            and bool(parts[0])
            and bool(parts[1])
            and is_valid_icon(parts[0], icons_dir)
            and is_valid_icon(parts[1], icons_dir)
        )
    if resolve_procedural_icon_key(norm) is not None:
        return True
    return resolve_svg_icon_path(name, icons_dir=icons_dir) is not None


def format_icon_catalog_table(icons_dir: str | Path = DEFAULT_ICONS_DIR) -> str:
    """Format a human-readable CLI table of all Mechanical, Electrical, Safety, and SVG icons."""
    lines = [
        f"{'ICON KEY':<24} | {'CATEGORY':<12} | {'ALIASES':<28} | DESCRIPTION",
        "-" * 114,
    ]
    category_order = {"mechanical": 0, "electrical": 1, "safety": 2}
    sorted_meta = sorted(
        ICON_METADATA_REGISTRY.values(),
        key=lambda m: (category_order.get(m.category, 99), m.name),
    )
    for meta in sorted_meta:
        alias_str = ", ".join(meta.aliases) if meta.aliases else "-"
        lines.append(
            f"{meta.name:<24} | {meta.category:<12} | {alias_str:<28} | {meta.description}"
        )

    avail = list_available_icons(icons_dir)
    lines.append("-" * 114)
    lines.append(
        "Tip: Pair any Profile + Drive side-by-side with '+' (e.g. icon='screw_button+torx' or drive_icon='torx')."
    )
    if avail["svg"]:
        lines.append(
            f"External SVG files in {Path(icons_dir).name}/: {', '.join(avail['svg'])}"
        )
    return "\n".join(lines)


def export_icon_catalog_svg(
    output_path: str | Path = DEFAULT_ICONS_DIR / "ICON_CATALOG.svg",
    icons_dir: str | Path = DEFAULT_ICONS_DIR,
    columns: int = 7,
) -> Path:
    """
    Render a visual SVG contact sheet of all registered Mechanical, Electrical,
    and Safety icons so you can preview the entire library side-by-side.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    cell_w = 28.0
    cell_h = 30.0
    icon_box = 14.0

    exporter = ExportSVG(unit=Unit.MM, line_weight=0.18)
    exporter.add_layer(
        "CardFrame",
        fill_color=Color(0.14, 0.16, 0.20),
        line_color=Color(0.28, 0.32, 0.38),
    )
    exporter.add_layer(
        "Mechanical",
        fill_color=Color(0.95, 0.96, 0.98),
        line_color=Color(0.95, 0.96, 0.98),
    )
    exporter.add_layer(
        "Electrical",
        fill_color=Color(0.38, 0.78, 0.98),
        line_color=Color(0.38, 0.78, 0.98),
    )
    exporter.add_layer(
        "Safety",
        fill_color=Color(0.98, 0.75, 0.24),
        line_color=Color(0.98, 0.75, 0.24),
    )
    exporter.add_layer(
        "LabelText",
        fill_color=Color(0.82, 0.85, 0.90),
        line_color=Color(0.82, 0.85, 0.90),
    )

    category_order = {"mechanical": 0, "electrical": 1, "safety": 2}
    sorted_meta = sorted(
        ICON_METADATA_REGISTRY.values(),
        key=lambda m: (category_order.get(m.category, 99), m.name),
    )

    layer_map = {
        "mechanical": "Mechanical",
        "electrical": "Electrical",
        "safety": "Safety",
    }

    for idx, meta in enumerate(sorted_meta):
        col = idx % columns
        row = idx // columns
        cx = col * cell_w
        cy = -row * cell_h

        with BuildSketch() as card_sk:
            Rectangle(cell_w - 2.4, cell_h - 2.4)
            fillet(card_sk.vertices(), radius=1.8)
        exporter.add_shape(
            card_sk.sketch.moved(Location((cx, cy, 0.0))), layer="CardFrame"
        )

        unit_sk = get_unit_icon(meta.name, str(icons_dir))
        if unit_sk is not None:
            placed_icon = unit_sk.scale(icon_box).moved(
                Location((cx, cy + 3.2, 0.0))
            )
            exporter.add_shape(
                placed_icon, layer=layer_map.get(meta.category, "Mechanical")
            )

        with BuildSketch() as lbl_sk:
            Text(
                meta.name,
                font_size=2.3,
                font_style=FontStyle.BOLD,
                align=(Align.CENTER, Align.CENTER),
            )
        lbl_bb = lbl_sk.sketch.bounding_box()
        max_lbl_w = cell_w - 4.4
        lbl_shape = lbl_sk.sketch
        if lbl_bb.size.X > max_lbl_w and lbl_bb.size.X > 0:
            lbl_shape = lbl_shape.scale(max_lbl_w / lbl_bb.size.X)
        s_bb = lbl_shape.bounding_box()
        lbl_cx = (s_bb.min.X + s_bb.max.X) / 2.0
        lbl_cy = (s_bb.min.Y + s_bb.max.Y) / 2.0
        exporter.add_shape(
            lbl_shape.moved(Location((cx - lbl_cx, cy - 9.2 - lbl_cy, 0.0))),
            layer="LabelText",
        )

    exporter.write(str(out_file))
    return out_file.resolve()
