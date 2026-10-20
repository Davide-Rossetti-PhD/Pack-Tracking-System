"""
Item Tracking Pipeline.

Loads two datasets (Operational Events + Routing Events) in Excel or CSV format,
runs a merge-and-sort flow, and produces a JSON dictionary ready for the dashboard.

Flow:
  STEP 1  Load the two datasets
  STEP 2  Reduce Operational Events to identifying columns + operational flow
  STEP 3  Reduce Routing Events to selected columns and clean timestamps
  STEP 4  Build the unified dictionary (operational + routing)
  STEP 5  Sort all events by timestamp
  STEP 6  Export to JSON structure (name / time / type)
"""

import io
import json
import sys
from collections import OrderedDict
from datetime import datetime

import pandas as pd


# =============================================================================
# Configuration
# =============================================================================

ID_COLUMNS = [
    "item_label",
    "item_id",
    "site_id",
    "deadline_time_local",
]

OPERATIONAL_FLOW = [
    "inbound_unload_time_local",
    "sorter_induct_time_local",
    "sorter_divert_time_local",
    "secondary_scan_time_local",
    "stack_time_local",
    "outbound_staging_time_local",
    "loaded_time_local",
    "depart_time_local",
]

ROUTING_COLUMNS = [
    "item_label",
    "equipment_id",
    "site_code",
    "event_type",
    "scan_source",
    "induct_time_local",
    "event_time_local",
]

INFO_KEYS = {"item_id", "site_id"}
DEADLINE_KEY = "deadline_time_local"

# Site filter — set to your site code, or None to skip filtering
SITE_FILTER = None


# =============================================================================
# Robust loading (CSV or Excel)
# =============================================================================

def load_data(source, filename=None) -> pd.DataFrame:
    """
    Load a DataFrame from a path/file object, auto-detecting CSV or Excel.
    """
    name = (filename or getattr(source, "filename", None) or str(source)).lower()

    if hasattr(source, "read"):
        raw = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except (OSError, ValueError):
                pass
        buffer_factory = lambda: io.BytesIO(raw)
    else:
        with open(source, "rb") as fh:
            raw = fh.read()
        buffer_factory = lambda: io.BytesIO(raw)

    if name.endswith(".csv"):
        df = pd.read_csv(buffer_factory())
    else:
        df = pd.read_excel(buffer_factory())
        if len(df.columns) == 1 and "," in str(df.columns[0]):
            col_name = df.columns[0]
            rows = df[col_name].tolist()
            csv_text = col_name + "\n" + "\n".join(str(r) for r in rows)
            df = pd.read_csv(io.StringIO(csv_text))

    return df


# =============================================================================
# STEP 2: Reduce Operational Events
# =============================================================================

def reduce_operational(df_ops: pd.DataFrame) -> pd.DataFrame:
    keep_cols = ID_COLUMNS + OPERATIONAL_FLOW
    missing = [c for c in keep_cols if c not in df_ops.columns]
    if missing:
        raise ValueError(
            "The Operational Events file is missing columns: " + ", ".join(missing)
        )

    df = df_ops[keep_cols].copy()
    if SITE_FILTER:
        df = df[df["site_id"].astype(str).str.upper() == SITE_FILTER.upper()].copy()
    return df


# =============================================================================
# STEP 3: Reduce Routing Events
# =============================================================================

def reduce_routing(df_routing: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in ROUTING_COLUMNS if c not in df_routing.columns]
    if missing:
        raise ValueError(
            "The Routing Events file is missing columns: " + ", ".join(missing)
        )

    df = df_routing[ROUTING_COLUMNS].copy()

    for col in ["induct_time_local", "event_time_local"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(r" \w+/\w+$", "", regex=True)   # strip timezone names
            .str.replace(r"\.\d+$", "", regex=True)       # strip fractional seconds
        )
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


# =============================================================================
# STEP 4: Unified dictionary
# =============================================================================

def build_unified(df_ops: pd.DataFrame, df_routing: pd.DataFrame) -> dict:
    packages = {}

    for _, row in df_ops.iterrows():
        label = row["item_label"]
        packages[label] = {}
        for col in df_ops.columns:
            if col != "item_label":
                packages[label][col] = row[col]

    for _, row in df_routing.iterrows():
        pid = row["item_label"]
        if pid in packages:
            key = f"{row['scan_source']}_{row['event_type']}_time_local"
            ts = row["event_time_local"]
            packages[pid][key] = (
                ts.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts) else None
            )

    return packages


# =============================================================================
# STEP 5: Sort all events by timestamp
# =============================================================================

def build_sorted(packages: dict) -> dict:
    sorted_packages = {}

    for label, data in packages.items():
        info = {}
        events_raw = {}
        deadline = None

        for key, value in data.items():
            if key in INFO_KEYS:
                info[key] = value
            elif key == DEADLINE_KEY:
                deadline = value
            else:
                if pd.notna(value) and value is not None and str(value).strip() != "":
                    if isinstance(value, str):
                        try:
                            ts = pd.to_datetime(value).to_pydatetime()
                        except (ValueError, TypeError):
                            continue
                    elif isinstance(value, datetime):
                        ts = value
                    else:
                        try:
                            ts = pd.to_datetime(value).to_pydatetime()
                        except (ValueError, TypeError):
                            continue
                    events_raw[key] = ts

        sorted_events = OrderedDict(sorted(events_raw.items(), key=lambda x: x[1]))

        sorted_packages[label] = {
            "item_id": info.get("item_id", ""),
            "site_id": info.get("site_id", ""),
            "deadline": deadline,
            "events": sorted_events,
        }

    return sorted_packages


# =============================================================================
# STEP 6: Final JSON structure
# =============================================================================

def to_dashboard_dict(sorted_packages: dict) -> dict:
    output = {}
    for label, pkg in sorted_packages.items():
        events = []
        for key, ts in pkg["events"].items():
            events.append(
                {
                    "name": key,
                    "time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "routing" if ("PRIMARY" in key or "SECONDARY" in key) else "operational",
                }
            )
        output[label] = {
            "item_id": pkg["item_id"],
            "site_id": pkg["site_id"],
            "deadline": str(pkg["deadline"]) if pkg["deadline"] else None,
            "events": events,
        }
    return output


# =============================================================================
# End-to-end orchestration
# =============================================================================

def run_pipeline(ops_source, routing_source,
                 ops_name=None, routing_name=None) -> dict:
    """Run the entire flow and return the dashboard dictionary."""
    df_ops = load_data(ops_source, ops_name)
    df_routing = load_data(routing_source, routing_name)

    df_ops_r = reduce_operational(df_ops)
    df_routing_r = reduce_routing(df_routing)

    packages = build_unified(df_ops_r, df_routing_r)
    sorted_packages = build_sorted(packages)
    return to_dashboard_dict(sorted_packages)


def run_pipeline_to_json(ops_source, routing_source,
                         ops_name=None, routing_name=None, indent=1) -> str:
    data = run_pipeline(ops_source, routing_source, ops_name, routing_name)
    return json.dumps(data, ensure_ascii=False, indent=indent)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python pipeline.py <operational_events_file> <routing_events_file> [-o output.json]")
        sys.exit(1)

    ops_file = sys.argv[1]
    routing_file = sys.argv[2]
    out_file = None
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            out_file = sys.argv[idx + 1]

    result_json = run_pipeline_to_json(ops_file, routing_file)

    if out_file:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(result_json)
        print(f"Written {out_file} ({len(json.loads(result_json))} items)")
    else:
        print(result_json)
