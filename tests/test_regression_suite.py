from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import lib3mf
import pytest
from build123d import *

from binforge import BinForgeConfig, BinForgeEngine, generate_binforge_batch


def _inspect_3mf_mesh_objects(file_path: Path) -> list[tuple[str, int, int]]:
    """Return list of (name, vertex_count, triangle_count) for all mesh objects in a .3mf file."""
    wrapper = lib3mf.Wrapper()
    model = wrapper.CreateModel()
    reader = model.QueryReader("3mf")
    reader.ReadFromFile(str(file_path))

    meshes: list[tuple[str, int, int]] = []
    it = model.GetMeshObjects()
    while it.MoveNext():
        mesh = it.GetCurrentMeshObject()
        meshes.append(
            (mesh.GetName(), mesh.GetVertexCount(), mesh.GetTriangleCount())
        )
    return meshes


class TestGoldenMultiSystemRegression:
    """Validate deterministic geometric invariants across Cullenect, Akro-Mils, and Gladiator blanks."""

    @pytest.mark.parametrize(
        "cfg,expected_w,expected_h,expected_z,min_solids",
        [
            (
                BinForgeConfig(
                    blank_type="cullenect_1u",
                    title="M3 x 8",
                    subtitle="SHCS",
                    icon="bolt",
                ),
                36.0,
                11.0,
                1.20,
                9,
            ),
            (
                BinForgeConfig(
                    blank_type="cullenect_2u",
                    title="10k Resistors",
                    subtitle="1/4W 1% Metal Film",
                    icon="warning",
                ),
                78.0,
                11.0,
                1.20,
                25,
            ),
            (
                BinForgeConfig(
                    blank_type="akro_30220",
                    title="1/4-20 x 1\"",
                    subtitle="Hex Cap Grade 8",
                    icon="bolt",
                ),
                50.0,
                22.0,
                1.40,
                15,
            ),
            (
                BinForgeConfig(
                    blank_type="gladiator_small",
                    title="M6 Flange Nut",
                    subtitle="Serrated DIN 6923",
                    icon="nut",
                ),
                48.0,
                18.0,
                1.40,
                15,
            ),
        ],
    )
    def test_multi_system_label_geometry_invariants(
        self,
        cfg: BinForgeConfig,
        expected_w: float,
        expected_h: float,
        expected_z: float,
        min_solids: int,
    ):
        engine = BinForgeEngine(cfg)
        blank = engine.build_blank()
        faces_2d, solids_3d = engine.build_artwork()

        # 1. Blank dimensions
        blank_bb = blank.bounding_box()
        assert blank_bb.size.X == pytest.approx(expected_w, abs=1e-2)
        assert blank_bb.size.Y == pytest.approx(expected_h, abs=1e-2)
        assert blank_bb.size.Z == pytest.approx(expected_z, abs=1e-2)

        # 2. Artwork counts & Z placement (sits cleanly on z = plate_z .. plate_z + art_thickness)
        assert len(faces_2d) == len(solids_3d)
        assert len(solids_3d) >= min_solids
        art_bb = Compound(children=solids_3d).bounding_box()
        assert art_bb.min.Z == pytest.approx(expected_z, abs=1e-3)
        assert art_bb.max.Z == pytest.approx(
            expected_z + cfg.art_thickness, abs=1e-3
        )

        # 3. Artwork stays strictly within unobstructed usable X and Y margins
        assert art_bb.min.X >= -engine.usable_w / 2.0 - 1e-2
        assert art_bb.max.X <= engine.usable_w / 2.0 + 1e-2
        assert art_bb.min.Y >= -engine.usable_h / 2.0 - 1e-2
        assert art_bb.max.Y <= engine.usable_h / 2.0 + 1e-2


@pytest.fixture(scope="module")
def batch_output_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("binforge_regression_dist")
    inventory = [
        BinForgeConfig(
            blank_type="cullenect_1u", title="M3 x 8", subtitle="SHCS", icon="bolt"
        ),
        # Duplicate/colliding slug test ("M3-8" -> "m3_8" vs "M3 8" -> "m3_8")
        BinForgeConfig(
            blank_type="cullenect_1u", title="M3-8", subtitle="SHCS", icon="bolt"
        ),
        BinForgeConfig(
            blank_type="cullenect", title="M3 x 8", subtitle="SHCS", icon="nut"
        ),
        BinForgeConfig(
            blank_type="akro_30220",
            title="1/4-20 x 1\"",
            subtitle="Grade 8 Hex Cap",
            icon="bolt",
        ),
        BinForgeConfig(
            blank_type="gladiator_small",
            title="M6 Flange Nut",
            subtitle="Serrated DIN 6923",
            icon="nut",
        ),
        # No-icon and single-line edge case
        BinForgeConfig(
            blank_type="cullenect_1u", title=" Plain Label ", subtitle="", icon="none"
        ),
    ]
    generate_binforge_batch(inventory, output_dir=str(out_dir), max_plate_row_w=100.0)
    return out_dir


class TestEndToEndBatchRegression:
    """Full end-to-end regression suite validating 3MF, STEP, SVG, and Markdown catalog outputs."""

    def test_all_expected_files_exist_and_non_empty(self, batch_output_dir: Path):
        catalog = batch_output_dir / "catalog.md"
        assert catalog.is_file() and catalog.stat().st_size > 100

        expected_slugs = [
            "label_cullenect_1u_m3_x_8_shcs",
            "label_cullenect_1u_m3_8_shcs",
            "label_cullenect_1u_m3_x_8_shcs_2",
            "label_akro_30220_1_4_20_x_1_grade_8_hex_cap",
            "label_gladiator_small_m6_flange_nut_serrated_din_6923",
            "label_cullenect_1u_plain_label",
        ]

        for slug in expected_slugs:
            f_3mf = batch_output_dir / "3mf" / f"{slug}.3mf"
            f_step = batch_output_dir / "3mf" / f"{slug}.step"
            f_plan = batch_output_dir / "svg" / f"{slug}_plan.svg"
            f_iso = batch_output_dir / "svg" / f"{slug}_iso.svg"
            assert f_3mf.is_file() and f_3mf.stat().st_size > 1000
            assert f_step.is_file() and f_step.stat().st_size > 1000
            assert f_plan.is_file() and f_plan.stat().st_size > 200
            assert f_iso.is_file() and f_iso.stat().st_size > 200

        batch_3mf = batch_output_dir / "3mf" / "batch_plate.3mf"
        batch_step = batch_output_dir / "3mf" / "batch_plate.step"
        assert batch_3mf.is_file() and batch_3mf.stat().st_size > 5000
        assert batch_step.is_file() and batch_step.stat().st_size > 5000

    def test_3mf_files_have_strictly_two_mesh_objects(self, batch_output_dir: Path):
        """Ensure every .3mf file (individual and batch plate) has strictly 2 objects: Base and Artwork."""
        for f_3mf in (batch_output_dir / "3mf").glob("*.3mf"):
            meshes = _inspect_3mf_mesh_objects(f_3mf)
            assert len(meshes) == 2, (
                f"{f_3mf.name} should have 2 mesh objects, got {len(meshes)}"
            )
            names = [m[0] for m in meshes]
            assert "Base" in names
            assert "Artwork" in names
            for name, v_cnt, t_cnt in meshes:
                assert v_cnt > 8, f"{f_3mf.name}:{name} has too few vertices ({v_cnt})"
                assert t_cnt > 12, (
                    f"{f_3mf.name}:{name} has too few triangles ({t_cnt})"
                )

    def test_step_roundtrip_preserves_dimensions_and_solids(
        self, batch_output_dir: Path
    ):
        step_akro = (
            batch_output_dir
            / "3mf"
            / "label_akro_30220_1_4_20_x_1_grade_8_hex_cap.step"
        )
        imported_akro = import_step(str(step_akro))
        bb_akro = imported_akro.bounding_box()
        assert bb_akro.size.X == pytest.approx(50.0, abs=1e-2)
        assert bb_akro.size.Y == pytest.approx(22.0, abs=1e-2)
        assert bb_akro.size.Z == pytest.approx(1.80, abs=1e-2)  # 1.40 base + 0.40 art

        step_batch = batch_output_dir / "3mf" / "batch_plate.step"
        imported_batch = import_step(str(step_batch))
        bb_batch = imported_batch.bounding_box()
        assert bb_batch.size.X <= 100.0 + 1e-2
        assert bb_batch.size.Y > 40.0
        assert bb_batch.size.Z == pytest.approx(1.80, abs=1e-2)

    def test_svg_files_are_valid_xml_with_base_and_artwork_layers(
        self, batch_output_dir: Path
    ):
        for svg_file in (batch_output_dir / "svg").glob("*.svg"):
            tree = ET.parse(svg_file)
            root = tree.getroot()
            assert root.tag.endswith("svg")
            layer_ids = {
                elem.attrib.get("id")
                for elem in root.iter()
                if "id" in elem.attrib
            }
            assert "Base" in layer_ids, f"Missing Base layer in {svg_file.name}"
            assert "Artwork" in layer_ids, f"Missing Artwork layer in {svg_file.name}"
            assert "Hidden" not in layer_ids, (
                f"Unexpected Hidden layer clutter in {svg_file.name}"
            )

    def test_catalog_markdown_links_all_generated_svgs(self, batch_output_dir: Path):
        catalog_text = (batch_output_dir / "catalog.md").read_text(encoding="utf-8")
        assert "batch_plate.3mf" in catalog_text
        assert "batch_plate.step" in catalog_text
        assert "label_akro_30220_1_4_20_x_1_grade_8_hex_cap_plan.svg" in catalog_text
        assert "label_gladiator_small_m6_flange_nut_serrated_din_6923_plan.svg" in catalog_text
        assert catalog_text.count("<img src='./svg/") == 12
