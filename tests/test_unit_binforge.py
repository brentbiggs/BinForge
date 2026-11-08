from __future__ import annotations

import pytest
from build123d import *

from binforge import (
    AVAILABLE_BLANK_TYPES,
    ICON_ALIASES,
    ICON_METADATA_REGISTRY,
    PROCEDURAL_ICON_REGISTRY,
    BinForgeConfig,
    BinForgeEngine,
    BlankSpec,
    _cached_base_iso_projection,
    _cached_base_sketch,
    _cached_blank,
    _cached_fit_text,
    _cached_icon_solids,
    _cached_unit_icon,
    _center_sketch,
    _default_font,
    _pack_into_single_solid,
    _slugify,
    export_icon_catalog_svg,
    format_icon_catalog_table,
    lint_binforge_inventory,
    load_binforge_inventory,
    resolve_blank_spec,
)


class TestConfigAndHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("M3 x 12", "m3_x_12"),
            ("10k Resistors_1/4W 1% Metal Film", "10k_resistors_1_4w_1_metal_film"),
            ("  ///M4: Hex*Nut???  ", "m4_hex_nut"),
            ("DIN-985", "din_985"),
            ("", ""),
        ],
    )
    def test_slugify_sanitizes_special_characters(self, raw: str, expected: str):
        assert _slugify(raw) == expected

    def test_default_font_returns_non_empty_string(self):
        font = _default_font()
        assert isinstance(font, str)
        assert len(font) > 0

    def test_binforge_config_defaults(self):
        cfg = BinForgeConfig()
        assert cfg.blank_type == "cullenect_1u"
        assert cfg.art_thickness == pytest.approx(0.40)
        assert cfg.margin_x == pytest.approx(2.4)
        assert cfg.margin_y == pytest.approx(1.0)
        assert cfg.slot_gap == pytest.approx(1.5)


class TestModularBlankSpecsAndGeometry:
    @pytest.mark.parametrize("blank_type", AVAILABLE_BLANK_TYPES)
    def test_all_available_blank_types_resolve_and_build_valid_3d_solids(
        self, blank_type: str
    ):
        spec = resolve_blank_spec(blank_type)
        assert isinstance(spec, BlankSpec)
        engine = BinForgeEngine(BinForgeConfig(blank_type=blank_type))
        blank = engine.build_blank()
        assert blank.is_valid
        bb = blank.bounding_box()
        assert bb.size.X == pytest.approx(spec.plate_w, abs=1e-2)
        assert bb.size.Y == pytest.approx(spec.plate_h, abs=1e-2)
        assert bb.size.Z == pytest.approx(spec.plate_z, abs=1e-2)

    def test_unknown_blank_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown blank_type"):
            resolve_blank_spec("unknown_bin_system")

    def test_custom_blanks_json_and_flat_plate_style(self, tmp_path):
        import json
        from blank_library import build_blank_part, format_blank_catalog_table

        custom_json = tmp_path / "custom_blanks.json"
        custom_json.write_text(
            json.dumps(
                {
                    "aliases": {"packout": "packout_cup"},
                    "blanks": {
                        "packout_cup": {
                            "style": "flat_plate",
                            "description": "Custom magnetic flat tag",
                            "plate_w": 45.0,
                            "plate_h": 15.0,
                            "plate_z": 1.20,
                            "corner_r": 2.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        spec = resolve_blank_spec("packout", blanks_file=custom_json)
        assert spec.name == "packout_cup"
        assert spec.style == "flat_plate"
        assert spec.plate_w == pytest.approx(45.0)
        part = build_blank_part(spec)
        assert part.is_valid
        table = format_blank_catalog_table(custom_json)
        assert "packout_cup" in table
        assert "[alias: packout]" in table

    def test_cullenect_retention_groove_z_zones_and_long_edge_profile(self):
        """Verify 0.40mm bottom lip, 0.40mm inset groove on Y edges only, and 0.40mm top lip."""
        engine = BinForgeEngine(BinForgeConfig(blank_type="cullenect_1u"))
        blank = engine.build_blank()

        sec_bottom = section(blank, section_by=Plane.XY.offset(0.20))
        bb_bottom = sec_bottom.bounding_box()
        assert bb_bottom.size.X == pytest.approx(36.0, abs=1e-2)
        assert bb_bottom.size.Y == pytest.approx(11.0, abs=1e-2)

        sec_groove = section(blank, section_by=Plane.XY.offset(0.60))
        bb_groove = sec_groove.bounding_box()
        assert bb_groove.size.X == pytest.approx(36.0, abs=1e-2)
        assert bb_groove.size.Y == pytest.approx(10.6, abs=1e-2)

        sec_top = section(blank, section_by=Plane.XY.offset(1.00))
        bb_top = sec_top.bounding_box()
        assert bb_top.size.X == pytest.approx(36.0, abs=1e-2)
        assert bb_top.size.Y == pytest.approx(11.0, abs=1e-2)

    def test_akro_stepped_side_wings_and_raised_center_island(self):
        """Verify Akro-Mils blank has full width at wing_z and stepped visible_w on raised island."""
        engine = BinForgeEngine(BinForgeConfig(blank_type="akro_30220"))
        blank = engine.build_blank()
        spec = engine.blank_spec

        # Section inside side wing thickness (z = 0.40 mm): full 50.0 x 22.0 mm
        sec_wing = section(blank, section_by=Plane.XY.offset(0.40))
        bb_wing = sec_wing.bounding_box()
        assert bb_wing.size.X == pytest.approx(50.0, abs=1e-2)
        assert bb_wing.size.Y == pytest.approx(22.0, abs=1e-2)

        # Section inside raised center island (z = 1.10 mm): X is inset by 2 * wing_w (46.4 mm)
        sec_island = section(blank, section_by=Plane.XY.offset(1.10))
        bb_island = sec_island.bounding_box()
        assert bb_island.size.X == pytest.approx(spec.visible_w, abs=1e-2)
        assert bb_island.size.Y == pytest.approx(22.0, abs=1e-2)

    def test_gladiator_stepped_side_rails_and_bottom_lip(self):
        """Verify Gladiator blank steps in both X (side rails) and bottom Y (retention lip) above wing_z."""
        engine = BinForgeEngine(BinForgeConfig(blank_type="gladiator_small"))
        blank = engine.build_blank()
        spec = engine.blank_spec

        # Section at z = 0.40 mm: full 48.0 x 18.0 mm
        sec_wing = section(blank, section_by=Plane.XY.offset(0.40))
        bb_wing = sec_wing.bounding_box()
        assert bb_wing.size.X == pytest.approx(48.0, abs=1e-2)
        assert bb_wing.size.Y == pytest.approx(18.0, abs=1e-2)

        # Section at z = 1.10 mm: X is visible_w (44.4 mm) and Y is plate_h - latch_inset (17.7 mm)
        sec_island = section(blank, section_by=Plane.XY.offset(1.10))
        bb_island = sec_island.bounding_box()
        assert bb_island.size.X == pytest.approx(spec.visible_w, abs=1e-2)
        assert bb_island.size.Y == pytest.approx(
            spec.plate_h - spec.latch_inset, abs=1e-2
        )

    def test_blank_cache_returns_independent_part_wrappers(self):
        engine = BinForgeEngine(BinForgeConfig(blank_type="cullenect_1u"))
        b1 = engine.build_blank()
        b2 = engine.build_blank()
        b1.label = "CustomA"
        b2.label = "CustomB"
        assert b1.label == "CustomA"
        assert b2.label == "CustomB"
        assert _cached_blank.cache_info().hits >= 1


class TestLayoutOrchestration:
    @pytest.mark.parametrize(
        "blank_type,expected_w",
        [
            ("cullenect_1u", 36.0),
            ("cullenect_2u", 78.0),
            ("cullenect_3u", 120.0),
            ("cullenect_4u", 162.0),
            ("cullenect_5u", 204.0),
            ("cullenect_6u", 246.0),
        ],
    )
    def test_cullenect_explicit_preset_dimensions(
        self, blank_type: str, expected_w: float
    ):
        cfg = BinForgeConfig(blank_type=blank_type)
        engine = BinForgeEngine(cfg)
        assert engine.plate_w == pytest.approx(expected_w)
        assert engine.plate_h == pytest.approx(11.0)
        assert engine.plate_z == pytest.approx(1.20)
        assert engine.usable_w == pytest.approx(expected_w - 4.8)
        assert engine.usable_h == pytest.approx(9.0)

    def test_layout_with_valid_icon(self):
        cfg = BinForgeConfig(blank_type="cullenect_1u", icon="bolt")
        engine = BinForgeEngine(cfg)
        assert engine.icon_bounds is not None
        assert engine.icon_bounds["size"] == pytest.approx(7.5)
        assert engine.icon_bounds["center_x"] == pytest.approx(-11.85)
        assert engine.icon_bounds["center_y"] == pytest.approx(0.0)
        assert engine.text_bounds["x_min"] == pytest.approx(-6.6)
        assert engine.text_bounds["x_max"] == pytest.approx(15.6)
        assert engine.text_bounds["w"] == pytest.approx(22.2)
        assert engine.text_bounds["center_x"] == pytest.approx(4.5)

    @pytest.mark.parametrize("icon_name", ["none", "nonexistent_icon", ""])
    def test_layout_without_icon_uses_full_usable_width(self, icon_name: str):
        cfg = BinForgeConfig(blank_type="cullenect_1u", icon=icon_name)
        engine = BinForgeEngine(cfg)
        assert engine.icon_bounds is None
        assert engine.text_bounds["x_min"] == pytest.approx(-15.6)
        assert engine.text_bounds["x_max"] == pytest.approx(15.6)
        assert engine.text_bounds["w"] == pytest.approx(31.2)
        assert engine.text_bounds["center_x"] == pytest.approx(0.0)


class TestIconGeometry:
    @pytest.mark.parametrize(
        "icon_name",
        sorted(PROCEDURAL_ICON_REGISTRY.keys())
        + [
            "icons/capacitor.svg",
            "icons/magnet.svg",
            "icons/bearing.svg",
        ],
    )
    def test_unit_icons_are_centered_and_normalized(self, icon_name: str):
        sk = _cached_unit_icon(icon_name)
        assert sk is not None
        faces = sk.faces()
        assert len(faces) >= 1
        assert sum(f.area for f in faces) > 0.12
        bbox = sk.bounding_box()
        cx = (bbox.min.X + bbox.max.X) / 2.0
        cy = (bbox.min.Y + bbox.max.Y) / 2.0
        assert cx == pytest.approx(0.0, abs=1e-5)
        assert cy == pytest.approx(0.0, abs=1e-5)
        assert max(bbox.size.X, bbox.size.Y) == pytest.approx(1.0, abs=1e-5)

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("allen", "screw_hex"),
            ("bhcs", "screw_button"),
            ("fhcs", "screw_countersunk"),
            ("nyloc", "nut_lock"),
            ("tnut", "nut_tnut"),
            ("heatset", "insert_heatset"),
            ("star_washer", "washer_star"),
            ("internal_star_washer", "washer_star_internal"),
            ("cap", "capacitor"),
            ("elcap", "capacitor_electrolytic"),
            ("chip", "ic"),
            ("gnd", "ground"),
            ("esd", "high_voltage"),
        ],
    )
    def test_icon_aliases_resolve_to_canonical_unit_sketch(
        self, alias: str, canonical: str
    ):
        assert ICON_ALIASES[alias] == canonical
        sk_alias = _cached_unit_icon(alias)
        sk_canon = _cached_unit_icon(canonical)
        assert sk_alias is not None and sk_canon is not None
        assert len(sk_alias.faces()) == len(sk_canon.faces())

    def test_icon_catalog_table_and_svg_sheet_export(self, tmp_path):
        table = format_icon_catalog_table()
        assert "screw_phillips" in table
        assert "shcs_hex" in table
        assert "bhcs_torx" in table
        assert "fhcs_phillips" in table
        assert "nut_lock_top" in table
        assert "capacitor_electrolytic" in table
        assert "mechanical" in table
        assert "electrical" in table

        svg_sheet = tmp_path / "ICON_CATALOG.svg"
        out = export_icon_catalog_svg(svg_sheet)
        assert out.is_file() and out.stat().st_size > 5000

    def test_dynamic_profile_plus_drive_composite_and_drive_icon_field(self):
        # 1. Explicit '+' composite syntax
        comp_sk = _cached_unit_icon("screw_button+screw_torx")
        assert comp_sk is not None
        assert len(comp_sk.faces()) >= 2
        bb = comp_sk.bounding_box()
        assert max(bb.size.X, bb.size.Y) == pytest.approx(1.0, abs=1e-5)

        # 2. Separate drive_icon field on BinForgeConfig
        cfg = BinForgeConfig(
            blank_type="cullenect_1u",
            title="M3 x 10",
            subtitle="ISO 7380",
            icon="screw_button",
            drive_icon="torx",
        )
        assert cfg.icon == "screw_button+torx"
        engine = BinForgeEngine(cfg)
        faces_2d, solids_3d = engine.build_artwork()
        assert len(faces_2d) > 2
        assert len(solids_3d) == len(faces_2d)

    def test_external_svg_icon_extrudes_into_valid_3d_artwork(self):
        cfg = BinForgeConfig(
            blank_type="cullenect_1u",
            title="100nF 50V",
            subtitle="X7R Ceramic",
            icon="capacitor",
        )
        engine = BinForgeEngine(cfg)
        faces_2d, solids_3d = engine.build_artwork()
        assert len(faces_2d) > 2
        assert len(solids_3d) == len(faces_2d)

    def test_bolt_icon_is_single_manifold_face(self):
        bolt_sk = _cached_unit_icon("bolt")
        assert bolt_sk is not None
        assert len(bolt_sk.faces()) == 1

    def test_spring_icon_is_single_connected_rounded_manifold_face(self):
        spring_sk = _cached_unit_icon("spring")
        assert spring_sk is not None
        assert len(spring_sk.faces()) == 1
        assert len(spring_sk.faces()[0].wires()) == 1

    def test_nut_icon_has_hex_outer_and_circular_inner_wire(self):
        nut_sk = _cached_unit_icon("nut")
        assert nut_sk is not None
        faces = nut_sk.faces()
        assert len(faces) == 1
        assert len(faces[0].wires()) == 2

    def test_warning_icon_has_nozzle_printable_feature_sizes(self):
        cfg = BinForgeConfig(blank_type="cullenect_1u", icon="warning")
        engine = BinForgeEngine(cfg)
        icon_sk = engine._build_icon_sketch()
        assert icon_sk is not None
        faces = sorted(icon_sk.faces(), key=lambda f: f.area)
        assert len(faces) == 3
        dot_bb = faces[0].bounding_box()
        bar_bb = faces[1].bounding_box()
        assert dot_bb.size.X >= 0.55
        assert dot_bb.size.Y >= 0.55
        assert bar_bb.size.X >= 0.55


class TestTypographyAndFitting:
    def test_proportional_text_fitting_constrains_long_strings(self):
        cfg = BinForgeConfig(
            blank_type="cullenect_1u",
            title="Extremely Long Fastener Title That Must Shrink",
            subtitle="Super Long Subtitle Specification Text",
            icon="bolt",
        )
        engine = BinForgeEngine(cfg)
        max_w = engine.text_bounds["w"]
        title_sk = engine._fit_text_sketch(cfg.title, max_w, cfg.target_title_h)
        sub_sk = engine._fit_text_sketch(cfg.subtitle, max_w, cfg.target_sub_h)
        assert title_sk is not None
        assert sub_sk is not None
        assert title_sk.bounding_box().size.X <= max_w + 1e-3
        assert sub_sk.bounding_box().size.X <= max_w + 1e-3

    @pytest.mark.parametrize(
        "title,subtitle",
        [
            ("M3 x 12", ""),
            ("", "BHCS"),
            ("   ", "   "),
            ("", ""),
        ],
    )
    def test_empty_and_single_line_text_guards(self, title: str, subtitle: str):
        cfg = BinForgeConfig(
            blank_type="cullenect_1u", title=title, subtitle=subtitle, icon="bolt"
        )
        engine = BinForgeEngine(cfg)
        faces_2d, solids_3d = engine.build_artwork()
        if not title.strip() and not subtitle.strip():
            assert len(faces_2d) == 1
            assert len(solids_3d) == 1
        else:
            assert len(faces_2d) > 1
            assert len(solids_3d) > 1
            text_faces = engine._build_text_faces()
            bb = Compound(children=text_faces).bounding_box()
            assert (bb.min.Y + bb.max.Y) / 2.0 == pytest.approx(0.0, abs=1e-3)

    def test_two_line_text_is_optically_centered_and_non_overlapping(self):
        cfg = BinForgeConfig(
            blank_type="cullenect_1u", title="M3 x 12", subtitle="BHCS", icon="bolt"
        )
        engine = BinForgeEngine(cfg)
        text_faces = engine._build_text_faces()
        assert len(text_faces) > 0
        comp = Compound(children=text_faces)
        bb = comp.bounding_box()
        assert (bb.min.Y + bb.max.Y) / 2.0 == pytest.approx(0.0, abs=1e-2)
        assert bb.size.Y <= engine.usable_h + 1e-3
        assert (bb.min.X + bb.max.X) / 2.0 == pytest.approx(
            engine.text_bounds["center_x"], abs=1e-2
        )


class TestSolidPackingFor3MF:
    def test_pack_into_single_solid_preserves_shells_and_volume(self):
        s1 = Box(2, 2, 1)
        s2 = Box(2, 2, 1).moved(Location((5, 0, 0)))
        s3 = Box(2, 2, 1).moved(Location((10, 0, 0)))
        packed = _pack_into_single_solid(
            [s1, s2, s3], label="Artwork", color=Color(1, 1, 1)
        )
        assert len(packed.solids()) == 1
        assert len(packed.shells()) == 3
        assert len(packed.faces()) == 18
        assert packed.volume == pytest.approx(12.0, rel=1e-4)
        assert packed.label == "Artwork"


class TestSampleInventoryLoader:
    def test_load_fasteners_metric_csv(self):
        items = load_binforge_inventory("examples/fasteners_metric.csv")
        assert len(items) == 8
        assert items[0].title == "M2.5 x 6"
        assert items[0].icon == "bolt"
        assert items[-1].blank_type == "cullenect_2u"

    def test_load_electronics_lab_json(self):
        items = load_binforge_inventory("examples/electronics_lab.json")
        assert len(items) == 6
        assert items[0].icon == "resistor"
        assert items[1].icon == "capacitor"
        assert items[4].art_thickness == pytest.approx(0.60)
        assert items[5].blank_type == "cullenect_3u"

    def test_load_akro_and_gladiator_bins_csv(self):
        items = load_binforge_inventory("examples/akro_and_gladiator_bins.csv")
        assert len(items) == 7
        assert items[0].blank_type == "akro_30210"
        assert items[4].blank_type == "gladiator_small"
        assert items[6].blank_type == "gladiator_large"

    def test_load_feature_showcase_csv(self):
        items = load_binforge_inventory("examples/feature_showcase.csv")
        assert len(items) == 10
        assert items[3].title == "FULL WIDTH" and items[3].subtitle == ""
        assert items[4].title == "" and items[4].subtitle == "SUBTITLE ONLY"
        assert items[5].title == "" and items[5].subtitle == "" and items[5].icon == "warning"
        assert items[8].blank_type == "akro_30220"
        assert items[9].blank_type == "gladiator_medium"

    def test_unsupported_extension_raises_value_error(self, tmp_path):
        bad_file = tmp_path / "inventory.txt"
        bad_file.write_text("hello", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported inventory format"):
            load_binforge_inventory(bad_file)


class TestDryRunLinter:
    def test_clean_inventory_produces_zero_warnings(self):
        items = load_binforge_inventory("examples/akro_and_gladiator_bins.csv")
        report = lint_binforge_inventory(items, max_plate_row_w=180.0)
        assert len(report.items) == 7
        assert report.total_warnings == 0
        assert report.plate_rows >= 2
        summary = report.format_summary()
        assert "Warnings: 0" in summary

    def test_linter_flags_printability_and_collision_warnings(self):
        items = [
            BinForgeConfig(
                blank_type="cullenect_1u",
                title="Extremely Long Title That Shrinks Below Nozzle Limit",
                subtitle="SHCS",
                icon="bolt",
            ),
            BinForgeConfig(
                blank_type="cullenect_1u",
                title="M3 x 8",
                subtitle="SHCS",
                icon="unknown_custom_icon",
                art_thickness=0.20,
            ),
            BinForgeConfig(
                blank_type="cullenect_1u",
                title="M3 x 8",
                subtitle="SHCS",
                icon="bolt",
            ),
            BinForgeConfig(
                blank_type="cullenect_1u",
                title="",
                subtitle="",
                icon="none",
            ),
        ]
        report = lint_binforge_inventory(items, max_plate_row_w=180.0)
        assert report.total_warnings >= 5
        assert any("Title shrinks" in w for w in report.items[0].warnings)
        assert any("Unknown icon" in w for w in report.items[1].warnings)
        assert any("art_thickness" in w for w in report.items[1].warnings)
        assert any("Duplicate slug" in w for w in report.items[2].warnings)
        assert any("no text or icon" in w for w in report.items[3].warnings)
