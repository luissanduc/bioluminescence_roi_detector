import argparse
import json
import os
import re
from typing import Dict, List, Optional, Tuple


INSTRUMENT_CM_PER_PIXEL = {
    "ivis 50": 0.010253906250,
    "ivis50": 0.010253906250,
    "ivis 200": 0.011562500000,
    "ivis200": 0.011562500000,
}

DEFAULT_CM_PER_PIXEL = 0.010253906250


def read_lines_if_exists(file_path: str) -> List[str]:
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", errors="ignore") as f:
            return f.readlines()
    except Exception:
        return []


def extract_field_value(lines: List[str], field_name: str) -> Optional[str]:
    prefix = f"{field_name.lower()}:"
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped.split(":", 1)[-1].strip()
    return None


def extract_existing_roi_cm_per_pixel(lines: List[str]) -> Optional[float]:
    values: List[float] = []
    for line in lines:
        if "cm per pixel=" not in line:
            continue
        m = re.search(r"cm per pixel=([0-9]*\.?[0-9]+)", line)
        if not m:
            continue
        try:
            values.append(float(m.group(1)))
        except ValueError:
            continue
    if not values:
        return None
    return round(sum(values) / len(values), 12)


def resolve_cm_per_pixel(folder_path: str) -> Dict[str, object]:
    analyzed_path = os.path.join(folder_path, "AnalyzedClickInfo.txt")
    click_path = os.path.join(folder_path, "ClickInfo.txt")

    analyzed_lines = read_lines_if_exists(analyzed_path)
    click_lines = read_lines_if_exists(click_path)
    all_text = "\n".join(analyzed_lines + click_lines).lower()

    # Priority 1: explicit instrument-like metadata keys.
    evidence_fields = [
        ("Instrument", extract_field_value(analyzed_lines, "Instrument") or extract_field_value(click_lines, "Instrument")),
        (
            "System Configuration",
            extract_field_value(analyzed_lines, "System Configuration")
            or extract_field_value(click_lines, "System Configuration"),
        ),
        ("Lens Type", extract_field_value(analyzed_lines, "Lens Type") or extract_field_value(click_lines, "Lens Type")),
    ]

    for field_name, field_value in evidence_fields:
        if not field_value:
            continue
        field_lower = field_value.lower()
        for key, cm_value in INSTRUMENT_CM_PER_PIXEL.items():
            if key in field_lower:
                return {
                    "folder": folder_path,
                    "cm_per_pixel": cm_value,
                    "instrument_guess": key,
                    "source": f"{field_name}",
                    "evidence": field_value,
                    "default_used": False,
                }

    # Priority 2: free-text scan for wrapped metadata values such as
    # "System Configuration: IVIS 200" followed by "Spectrum" on next line.
    if "ivis 200" in all_text or "ivis200" in all_text:
        return {
            "folder": folder_path,
            "cm_per_pixel": INSTRUMENT_CM_PER_PIXEL["ivis 200"],
            "instrument_guess": "ivis 200",
            "source": "metadata-text",
            "evidence": "matched 'ivis 200' in metadata text",
            "default_used": False,
        }

    if "ivis 50" in all_text or "ivis50" in all_text:
        return {
            "folder": folder_path,
            "cm_per_pixel": INSTRUMENT_CM_PER_PIXEL["ivis 50"],
            "instrument_guess": "ivis 50",
            "source": "metadata-text",
            "evidence": "matched 'ivis 50' in metadata text",
            "default_used": False,
        }

    # Priority 3: use existing ROI entries if present.
    existing_roi_cm = extract_existing_roi_cm_per_pixel(analyzed_lines)
    if existing_roi_cm is not None:
        return {
            "folder": folder_path,
            "cm_per_pixel": existing_roi_cm,
            "instrument_guess": "unknown",
            "source": "existing-roi",
            "evidence": "averaged existing 'cm per pixel=' ROI values",
            "default_used": False,
        }

    # Final fallback.
    return {
        "folder": folder_path,
        "cm_per_pixel": DEFAULT_CM_PER_PIXEL,
        "instrument_guess": "unknown",
        "source": "default",
        "evidence": "no matching metadata or existing ROI cm/pixel found",
        "default_used": True,
    }


def find_candidate_folders(base_directory: str) -> List[str]:
    folders: List[str] = []
    for root, _dirs, files in os.walk(base_directory):
        if "AnalyzedClickInfo.txt" in files or "ClickInfo.txt" in files:
            folders.append(root)
    folders.sort()
    return folders


def print_report(results: List[Dict[str, object]]) -> None:
    print("folder\tcm_per_pixel\tsource\tevidence")
    for item in results:
        print(
            f"{item['folder']}\t{item['cm_per_pixel']:.12f}\t"
            f"{item['source']}\t{item['evidence']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Infer IVIS cm/pixel from AnalyzedClickInfo.txt and ClickInfo.txt "
            "for each folder under a base directory."
        )
    )
    parser.add_argument("base_directory", help="Root folder containing IVIS click subfolders")
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="Optional path to write JSON report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.path.isdir(args.base_directory):
        print(f"Error: '{args.base_directory}' is not a valid directory")
        return 1

    folders = find_candidate_folders(args.base_directory)
    if not folders:
        print("No folders containing AnalyzedClickInfo.txt or ClickInfo.txt were found.")
        return 1

    results = [resolve_cm_per_pixel(folder) for folder in folders]
    print_report(results)

    if args.json_path:
        with open(args.json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nJSON report written to: {args.json_path}")

    defaults = sum(1 for r in results if r.get("default_used"))
    print(f"\nSummary: {len(results)} folder(s), {defaults} fallback default(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
