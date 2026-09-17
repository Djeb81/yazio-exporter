# tools

Post-processing scripts that run *after* an export. They are not part of the
`yazio_exporter` package, are not installed by `uv tool install`, and import
nothing from it — they only read the JSON files an export leaves behind.

| Script | Reads | Writes |
|---|---|---|
| `build_dataset.py` | `days.json`, `weight.json`, `products.json`, `profile.json`, `nutrients.json` | `yazio-dataset.json` + `csv/*.csv` |
| `build_analysis.py` | `yazio-dataset.json` | `analyse.html` |
| `build_handoff.py` | `yazio-dataset.json`, `csv/*.csv` | `handoff.html` |

`build_dataset.py` is the entry point: the other two consume its output, so run
it first.

## Export directory

All three resolve the export directory from `YAZIO_EXPORT_DIR`, defaulting to
`~/yazio-export`:

```bash
yazio-exporter sync
python3 tools/build_dataset.py
python3 tools/build_analysis.py
python3 tools/build_handoff.py
```

```bash
YAZIO_EXPORT_DIR=/path/to/other/export python3 tools/build_dataset.py
```

## What `build_dataset.py` is for

`analysis.md` is generated for a reader. `yazio-dataset.json` is generated for a
downstream consumer (an LLM project, a notebook), so it carries the caveats that
a reader would otherwise have to know by heart:

- `weight.json` holds one value per date, but the API repeats the last known
  weigh-in, so the series is mostly carry-forward. Only `weigh_ins` are real
  measurements.
- The current day is still being logged; rows carry a `partial` flag.
- Days under 800 kcal are days that were barely logged, not days of fasting;
  they carry `below_tracking_threshold`.
- Low step counts usually mean the phone was not carried (`steps_suspect`).
- Micronutrient values are returned raw, with no unit declared per nutrient.

It also strips account identifiers, name and date of birth from the profile, so
the file can be handed to a third party. It still contains detailed health data.

## `build_analysis.py` options

The report is written in French. Both of its inputs are derived from the export
and can be overridden:

| Option | Default |
|---|---|
| `--start` | First day of the latest tracking run, i.e. after the last pause longer than 30 days |
| `--target` | The weight goal set in the app (`bodyvalue.weight`) |
| `--out` | `<export dir>/analyse.html` |

```bash
python3 tools/build_analysis.py --start 2026-09-01 --target 80
```

If the export carries no weight goal, the goal row and the projection are
omitted rather than guessed.
