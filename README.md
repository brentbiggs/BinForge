# BinForge

Parametric 3D-printable workshop bin label generator powered by [`build123d`](https://github.com/gumyr/build123d), supporting **Gridfinity Cullenect** (`1U`–`6U`), **Akro-Mils** (`30210`, `30220`, `30230`, `30240`), and **Gladiator** (`small`, `medium`, `large`) storage bins.

## Directory Structure

- `binforge.py` — Main CAD/SVG engine, batch build-plate packer, dry-run linter, and CLI
- `blanks.json` — Declarative catalog of bin label dimensions, retention features, and aliases
- `blank_library.py` — Pluggable 3D blank geometry builders (`cullenect_groove`, `akro_slot`, `gladiator_slot`, `flat_plate`)
- `icon_library.py` — Unified `0.4 mm` nozzle-safe Mechanical, Electrical, and Safety icon library (Profile, Drive/Top-Down, and Combined Profile+Drive views)
- `icons/` — External `.svg` icons and generated visual catalog sheet (`ICON_CATALOG.svg`)
- `examples/` — Sample `.csv` and `.json` label inventories
- `tests/` — Unit and end-to-end 3MF/STEP/SVG regression test suite

## Quick Start

```powershell
# List all configured bin blank presets
python binforge.py --list-blanks

# List all Mechanical, Electrical, Safety, and SVG icons
python binforge.py --list-icons

# Export visual SVG contact sheet of the entire icon library
python binforge.py --export-icon-catalog

# Dry-run / lint an inventory without writing 3D files
python binforge.py -i examples/fasteners_metric.csv --dry-run

# Generate individual + master build-plate .3mf, .step, .svg, and catalog.md
python binforge.py -i examples/fasteners_metric.csv -o dist/fasteners
```

## License

Released under the [MIT License](LICENSE).

