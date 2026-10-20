# Item Tracking Dashboard

A lightweight, self-contained web application for tracking items through a multi-stage logistics pipeline. It ingests two datasets — operational flow events and automated routing events — merges them into a unified, chronologically-sorted timeline per item, and serves an interactive dashboard for visual inspection, filtering, and JSON export.

Designed as an MVP: run `python app.py`, upload two files, and start analyzing.

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Try It with Sample Data](#try-it-with-sample-data)
- [Data Model](#data-model)
- [Pipeline Logic](#pipeline-logic)
- [Dashboard Features](#dashboard-features)
- [CLI Mode](#cli-mode)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Export for AI Analysis](#export-for-ai-analysis)
- [Dependencies](#dependencies)
- [License](#license)

---

## Architecture

```
┌──────────────┐     ┌──────────────┐
│  Operational  │     │   Routing    │
│  Events       │     │   Events     │
│  (Excel/CSV)  │     │  (Excel/CSV) │
└──────┬───────┘     └──────┬───────┘
       │                     │
       └────────┬────────────┘
                │
         ┌──────▼──────┐
         │  pipeline.py │  ← merge, sort, classify
         └──────┬──────┘
                │
         ┌──────▼──────┐
         │  JSON output │  ← unified timeline per item
         └──────┬──────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
 Dashboard   Download    AI Export
 (browser)   (.json)     (feed to LLM)
```

The Flask server (`app.py`) orchestrates the flow: it receives the two files via a web upload form, delegates processing to `pipeline.py`, stores the result in memory, and serves both the JSON and the interactive dashboard.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the app
python app.py

# 3. Browser opens automatically at http://localhost:8080
```

Upload the two data files → click **Generate JSON** → choose **Open Dashboard** or **Download JSON**.

---

## Try It with Sample Data

The `sample_data/` folder ships with **synthetic Excel files** (120 items, 264 routing events) generated with a fixed random seed for reproducibility:

| File | Rows | Description |
|------|------|-------------|
| `sample_operational_events.xlsx` | 120 | Full operational flow timestamps across 8 hours |
| `sample_routing_events.xlsx` | 264 | Routing events — ~35% Alpha, ~35% Beta, ~30% Conveyor |

Upload both files in the app to see the dashboard in action immediately. The data includes ~5% missing timestamps and ~15% Beta recirculation events for realism.

---

## Data Model

### Operational Events (Excel/CSV)

One row per item, tracking the item through sequential processing stages:

| Column | Type | Description |
|--------|------|-------------|
| `item_label` | string | Unique item identifier (join key) |
| `item_id` | string | Secondary identifier |
| `site_id` | string | Processing site code |
| `deadline_time_local` | datetime | Processing deadline |
| `inbound_unload_time_local` | datetime | Inbound unloading timestamp |
| `sorter_induct_time_local` | datetime | Sorter induction scan |
| `sorter_divert_time_local` | datetime | Sorter divert scan |
| `secondary_scan_time_local` | datetime | Secondary verification scan |
| `stack_time_local` | datetime | Stacking timestamp |
| `outbound_staging_time_local` | datetime | Outbound staging timestamp |
| `loaded_time_local` | datetime | Trailer loading timestamp |
| `depart_time_local` | datetime | Trailer departure timestamp |

### Routing Events (Excel/CSV)

Multiple rows per item (one per routing event), recording automated routing decisions:

| Column | Type | Description |
|--------|------|-------------|
| `item_label` | string | Item identifier (matches operational data) |
| `equipment_id` | string | Equipment that processed the item |
| `site_code` | string | Site where routing occurred |
| `event_type` | string | `INDUCTED` · `ROUTED` · `COMPLETED` · `RECIRCULATED` · `REROUTED` |
| `scan_source` | string | `PRIMARY` (Alpha router) or `SECONDARY` (Beta router) |
| `induct_time_local` | datetime | Induction timestamp |
| `event_time_local` | datetime | Event occurrence timestamp |

### Output JSON

The pipeline produces a flat dictionary keyed by `item_label`:

```json
{
  "PKG-A1419610": {
    "item_id": "CNT-877572",
    "site_id": "SITE-01",
    "deadline": "2025-10-15 17:40:38",
    "events": [
      {"name": "sorter_induct_time_local", "time": "2025-10-15 07:59:29", "type": "operational"},
      {"name": "PRIMARY_INDUCTED_time_local", "time": "2025-10-15 08:00:17", "type": "routing"},
      {"name": "PRIMARY_ROUTED_time_local", "time": "2025-10-15 08:00:21", "type": "routing"},
      ...
    ]
  }
}
```

---

## Pipeline Logic

The processing pipeline (`pipeline.py`) executes six sequential steps:

| Step | Operation | Detail |
|------|-----------|--------|
| 1 | **Load** | Auto-detect CSV vs Excel; handle edge cases (CSV-inside-Excel, mixed formats) |
| 2 | **Reduce operational** | Select identifying + flow columns; optionally filter by site |
| 3 | **Reduce routing** | Select routing columns; strip timezone suffixes; parse timestamps |
| 4 | **Merge** | Build unified dictionary per item; routing events generate dynamic keys (`{scan_source}_{event_type}_time_local`) |
| 5 | **Sort** | Chronologically sort all events per item using `OrderedDict` |
| 6 | **Classify & export** | Tag each event as `operational` or `routing`; serialize to JSON |

**Type classification rule**: an event is `routing` if its key contains `PRIMARY` or `SECONDARY`; everything else is `operational`.

---

## Dashboard Features

The interactive HTML dashboard (`static/dashboard.html`) provides:

- **Item list** (left panel) — searchable, filterable by routing type
- **Filters** — All / Alpha / Beta / Conveyor (based on `scan_source` in the routing events)
- **Timeline view** (center panel) — chronological event table with:
  - Human-readable stage names (via `event_mapping.json`)
  - Delta time between consecutive events
  - Event type badges (OP / RT)
  - Processing line assignments
- **Info cards** — site, deadline, router dwell time, event count
- **Event legend** — full mapping of event keys to stage names and processing lines
- **JSON export** — download the processed data directly from the dashboard header

---

## CLI Mode

Process files without starting the web server:

```bash
python pipeline.py <operational_file> <routing_file> [-o output.json]
```

**Examples:**

```bash
# Output to stdout
python pipeline.py sample_data/sample_operational_events.xlsx sample_data/sample_routing_events.xlsx

# Save to file
python pipeline.py data/ops.csv data/routing.csv -o dashboard_data.json
```

---

## Project Structure

```
pack-tracking-system/
├── app.py                  Flask web app — upload, process, serve dashboard
├── pipeline.py             Data processing pipeline (Excel/CSV → JSON)
├── event_mapping.json      Event key → stage name + processing line mapping
├── requirements.txt        Python dependencies (Flask, pandas, openpyxl)
├── templates/
│   └── upload.html         Upload page UI
├── static/
│   └── dashboard.html      Interactive dashboard (vanilla JS, no frameworks)
├── sample_data/
│   ├── sample_operational_events.xlsx
│   └── sample_routing_events.xlsx
├── .gitignore
├── LICENSE                 MIT
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Upload page |
| `POST` | `/process` | Process the two files, return JSON |
| `POST` | `/process?download=1` | Process and force file download |
| `GET` | `/last_result.json` | Latest processed JSON (for dashboard autoload) |
| `GET` | `/event_mapping.json` | Event mapping configuration |
| `GET` | `/dashboard` | Interactive dashboard |
| `GET` | `/dashboard?autoload=1` | Dashboard with auto-loaded latest result |
| `GET` | `/health` | Health check |

---

## Export for AI Analysis

Click **Export JSON** in the dashboard header to download the processed data. The JSON is self-contained and structured for direct consumption by any LLM or analysis tool — useful for:

- **Anomaly detection** — identify items with unusual event sequences or timing gaps
- **Bottleneck analysis** — find stages with consistently high dwell times
- **Flow optimization** — compare routing paths (Alpha vs Beta vs Conveyor)
- **SLA monitoring** — flag items approaching or exceeding their deadline

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| Flask | ≥ 3.0 | Web server and routing |
| pandas | ≥ 2.2 | Data loading and transformation |
| openpyxl | ≥ 3.1 | Excel file support |

Python 3.10+ required.

---

## License

[MIT](LICENSE)
