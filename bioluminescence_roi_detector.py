import os
import sys
import requests
import base64
import tempfile
import re
import argparse
from PIL import Image
import numpy as np
import traceback

# ---- README and Usage ----
"""
This script processes subdirectories containing 'AnalyzedClickInfo.txt' and 'photograph.TIF' files.
It uses the Roboflow API to detect regions of interest (ROIs) in bioluminescence images of mice
and updates the IVIS Living Image text files with detected ROI positions.

Usage:
    python bioluminescence_roi_detector.py <input_directory>

This will recursively process all subdirectories of <input_directory> that contain the required files.
Warning: This will overwrite existing ROI entries and Comment2 fields in the text files.

Setup:
    Set your Roboflow API key as an environment variable before running:
        export ROBOFLOW_API_KEY="your_api_key_here"

    Or create a .env file in the same directory with:
        ROBOFLOW_API_KEY=your_api_key_here

Example output for Comment2 field:
    Comment2:   D,V,X,X,D
    (5 ROIs: dorsal in positions 1 and 5, ventral in position 2, no detection in 3 and 4)
"""
# ---- README and Usage ----

# ---- Config ----
# Get API key from environment variable (never hardcode your key).
# Validation is deferred until runtime so CLI help and dry checks can run.
API_KEY = os.environ.get("ROBOFLOW_API_KEY")

# The public Roboflow model used for bioluminescence ROI detection.
# This model detects dorsal (D) and ventral (V) mouse positions.
# You can view the model at: https://universe.roboflow.com/luissandoval/mice-hlehy
# If you want to fine-tune or copy the model to your own Roboflow workspace, visit the link above.
PROJECT_ID = "mice-hlehy"
MODEL_VERSION = "8"

CONFIDENCE = 0.80
IOU_THRESHOLD = 0.5

# Instrument profiles define both cm/pixel and effective image geometry.
# Add new instruments here as needed.
INSTRUMENT_PROFILES = {
    "ivis 50": {
        "cm_per_pixel": 0.010253906250,
        "target_width": 2048,
        "target_height": 2048,
    },
    "ivis 200": {
        "cm_per_pixel": 0.011562500000,
        "target_width": 1920,
        "target_height": 1920,
    },
}

INSTRUMENT_ALIASES = {
    "ivis 50": "ivis 50",
    "ivis50": "ivis 50",
    "ivis 200": "ivis 200",
    "ivis200": "ivis 200",
}

DEFAULT_INSTRUMENT = "ivis 50"

# Fiducials were originally authored for a 2048-wide reference canvas.
REFERENCE_CANVAS_WIDTH = 2048.0
REFERENCE_FIDUCIAL_X = {1: 200, 2: 600, 3: 1000, 4: 1400, 5: 1800}


def require_api_key():
    """Return API key or exit with a clear setup message."""
    api_key = os.environ.get("ROBOFLOW_API_KEY") or API_KEY
    if api_key:
        return api_key
    print(
        "Error: ROBOFLOW_API_KEY environment variable is not set.\n"
        "Please set it before running this script:\n"
        "  export ROBOFLOW_API_KEY='your_api_key_here'\n"
        "You can get your API key at: https://app.roboflow.com/settings/api"
    )
    sys.exit(1)


def _profile_for_instrument(instrument_name):
    canonical = INSTRUMENT_ALIASES.get(instrument_name.lower())
    if canonical and canonical in INSTRUMENT_PROFILES:
        return canonical, INSTRUMENT_PROFILES[canonical]
    return None, None


def _read_lines_if_exists(file_path):
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", errors="ignore") as f:
            return f.readlines()
    except Exception:
        return []


def _extract_field_value(lines, field_name):
    """Extract the text after '<field_name>:' from the first matching line."""
    prefix = f"{field_name.lower()}:"
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped.split(":", 1)[-1].strip()
    return None


def _extract_existing_roi_cm_per_pixel(lines):
    """Read cm-per-pixel from pre-existing ROI lines when present."""
    values = []
    for line in lines:
        if "cm per pixel=" not in line:
            continue
        m = re.search(r"cm per pixel=([0-9]*\.?[0-9]+)", line)
        if m:
            try:
                values.append(float(m.group(1)))
            except ValueError:
                continue
    if not values:
        return None
    return round(sum(values) / len(values), 12)


# ---- Detect Instrument and Resolve cm/pixel ----
def get_cm_per_pixel_info(folder_path, analyzed_lines):
    """
    Resolve cm/pixel + target geometry from IVIS metadata using multiple sources and return
    provenance information:
    1) Instrument/System Configuration/Lens fields (AnalyzedClickInfo + ClickInfo)
    2) Existing ROI cm-per-pixel values in AnalyzedClickInfo
    3) IVIS-50 profile fallback
    """
    click_lines = _read_lines_if_exists(os.path.join(folder_path, "ClickInfo.txt"))
    all_text = "\n".join(analyzed_lines + click_lines).lower()

    evidence_fields = [
        ("Instrument", _extract_field_value(analyzed_lines, "Instrument") or _extract_field_value(click_lines, "Instrument")),
        (
            "System Configuration",
            _extract_field_value(analyzed_lines, "System Configuration")
            or _extract_field_value(click_lines, "System Configuration"),
        ),
        ("Lens Type", _extract_field_value(analyzed_lines, "Lens Type") or _extract_field_value(click_lines, "Lens Type")),
    ]

    for key, value in evidence_fields:
        if not value:
            continue
        value_lower = value.lower()
        for instrument_key in INSTRUMENT_ALIASES:
            if instrument_key in value_lower:
                canonical, profile = _profile_for_instrument(instrument_key)
                print(f"  Instrument profile resolved from metadata source '{key}'.")
                return {
                    "cm_per_pixel": profile["cm_per_pixel"],
                    "target_width": profile["target_width"],
                    "target_height": profile["target_height"],
                    "instrument": canonical,
                    "source": key,
                    "evidence": value,
                    "used_default": False,
                }

    # Some exports wrap system configuration to the next line (e.g., "IVIS 200\n Spectrum")
    if "ivis 200" in all_text or "ivis200" in all_text:
        profile = INSTRUMENT_PROFILES["ivis 200"]
        print("  Instrument profile inferred from metadata text.")
        return {
            "cm_per_pixel": profile["cm_per_pixel"],
            "target_width": profile["target_width"],
            "target_height": profile["target_height"],
            "instrument": "ivis 200",
            "source": "metadata-text",
            "evidence": "matched 'ivis 200' in metadata text",
            "used_default": False,
        }
    if "ivis 50" in all_text or "ivis50" in all_text:
        profile = INSTRUMENT_PROFILES["ivis 50"]
        print("  Instrument profile inferred from metadata text.")
        return {
            "cm_per_pixel": profile["cm_per_pixel"],
            "target_width": profile["target_width"],
            "target_height": profile["target_height"],
            "instrument": "ivis 50",
            "source": "metadata-text",
            "evidence": "matched 'ivis 50' in metadata text",
            "used_default": False,
        }

    existing_roi_cm = _extract_existing_roi_cm_per_pixel(analyzed_lines)
    if existing_roi_cm is not None:
        default_profile = INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT]
        print(f"  Using existing ROI cm/pixel from file: {existing_roi_cm:.12f}")
        return {
            "cm_per_pixel": existing_roi_cm,
            "target_width": default_profile["target_width"],
            "target_height": default_profile["target_height"],
            "instrument": "unknown",
            "source": "existing-roi",
            "evidence": "averaged existing 'cm per pixel=' values from ROI lines",
            "used_default": False,
        }

    default_profile = INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT]
    print(
        f"  Warning: Could not infer instrument-specific cm/pixel. "
        f"Using default {default_profile['cm_per_pixel']:.12f} cm/pixel "
        f"({default_profile['target_width']}x{default_profile['target_height']})."
    )
    return {
        "cm_per_pixel": default_profile["cm_per_pixel"],
        "target_width": default_profile["target_width"],
        "target_height": default_profile["target_height"],
        "instrument": DEFAULT_INSTRUMENT,
        "source": "default",
        "evidence": "no matching Instrument/System Configuration/Lens/ROI metadata",
        "used_default": True,
    }


# ---- Check for Saturated Images through the ClickInfo/AnalyzedClickInfo ----
def is_saturated_click(folder_path: str) -> bool:
    """
    Returns True if ClickInfo/AnalyzedClickInfo indicates luminescent saturation.
    Checks AnalyzedClickInfo.txt first, then falls back to ClickInfo.txt.
    """
    candidates = [
        os.path.join(folder_path, "AnalyzedClickInfo.txt"),
        os.path.join(folder_path, "ClickInfo.txt"),
    ]

    for fp in candidates:
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "r", errors="ignore") as f:
                for line in f:
                    if line.strip().lower().startswith("saturated:"):
                        val = line.split(":", 1)[-1].strip()
                        return val.startswith("1")
        except Exception:
            pass

    return False


# ---- Normalize TIFF and Save as PNG ----
def normalize_tif_to_png(input_path):
    """Convert a 16-bit TIFF to an 8-bit PNG for the Roboflow API."""
    img = Image.open(input_path)
    arr = np.array(img)

    arr_8bit = ((arr - arr.min()) * 255.0 / (arr.max() - arr.min())).astype(np.uint8)
    img_8bit = Image.fromarray(arr_8bit)

    temp_png = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    img_8bit.save(temp_png.name)
    return temp_png.name, img.size  # Return PNG path and original image size


# ---- Call Roboflow API ----
def call_roboflow_local_image(image_path, api_key):
    """Send an image to the Roboflow inference API and return predictions."""
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")

    url = (
        f"https://detect.roboflow.com/{PROJECT_ID}/{MODEL_VERSION}"
        f"?api_key={api_key}&confidence={CONFIDENCE}&overlap={IOU_THRESHOLD}"
    )
    res = requests.post(url, data=encoded, headers={"Content-Type": "application/x-www-form-urlencoded"})
    res.raise_for_status()
    return res.json()


# ---- ROI Position Encoding and Comment2 Update ----
def encode_roi_positions(assigned, total_rois=5):
    """Encode detected positions as a comma-separated string (e.g., 'D,V,X,X,D')."""
    pos_map = {"nsg_dorsal": "D", "nsg_ventral": "V"}
    encoding = ["X"] * total_rois
    for roi_num in range(1, total_rois + 1):
        pred = assigned.get(roi_num)
        if pred:
            encoding[roi_num - 1] = pos_map.get(pred.get("class", ""), "X")
    return f"{','.join(encoding)}"


def update_comment2(lines, encoding):
    """Update the Comment2 field in the IVIS text file with the ROI position encoding."""
    for i, line in enumerate(lines):
        if line.strip().startswith("*** User Label Name Set:"):
            for j, info in enumerate(lines[i:i + 16]):
                if info.strip().startswith("Comment2:"):
                    lines[i + j] = f"Comment2:\t{encoding}\n"
                    break
    return lines


# ---- Extract CAGE from Text Lines ----
def _return_cage(txt_lines):
    """Extract the cage identifier from Comment1 in the IVIS text file."""
    for i, line in enumerate(txt_lines):
        if line.strip().startswith("*** User Label Name Set:"):
            for info in txt_lines[i:i + 16]:
                if info.strip().startswith("Comment1:"):
                    comment1 = info.split(":", 1)[-1].strip()
                    cage = comment1.split("_")[0]
                    return cage
    return None


# ---- Normalize predictions to fixed output resolution ----
def normalize_predictions(predictions, original_size, target_width, target_height):
    """Scale bounding box coordinates from original size to instrument-specific target canvas."""
    orig_w, orig_h = original_size
    norm = []
    for pred in predictions:
        if pred["confidence"] < CONFIDENCE and pred.get("class", "") not in ["nsg_ventral", "nsg_dorsal"]:
            print(f"Skipping low confidence prediction: {pred}")
            continue
        scale_x = target_width / orig_w
        scale_y = target_height / orig_h
        norm.append({
            "x": pred["x"] * scale_x,
            "y": pred["y"] * scale_y,
            "width": pred["width"] * scale_x,
            "height": pred["height"] * scale_y,
            "confidence": pred["confidence"],
            "class": pred["class"]
        })
    return norm


# ---- Format ROI Entries ----
def make_roi_entry(index, pred, cm_per_pixel):
    """Format a single ROI entry string for the IVIS text file."""
    return (
        f"ROI {index}:zColorIndex=1;ROI Type=Measurement;ColorTable=BlueRedGreen;"
        f"Subject ROI=_none_;Subject ID=;Subject Label=;Bkg ROI=_none_;"
        f"LineSize=2.000000;Locked=0;PositionLocked=0;Shape=Square;"
        f"Xc={pred['x']:.12f};Yc={pred['y']:.12f};Width={pred['width']:.12f};Height={pred['height']:.12f};"
        f"Angle=0.0000;Label=ROI {index};cm per pixel={cm_per_pixel:.12f};ROIColor=16711680;"
    )


# ---- Insert ROI Block into File ----
def insert_rois_to_file(file_path, predictions, cm_per_pixel, target_width):
    """Assign predictions to fiducial ROI positions and write them to the IVIS text file."""
    # Fiducial x-coordinates for the 5 ROI positions, scaled to target width.
    scale_x = target_width / REFERENCE_CANVAS_WIDTH
    fiducials = {f"ROI {i}": (x * scale_x, 850) for i, x in REFERENCE_FIDUCIAL_X.items()}

    # Assign each prediction to the nearest fiducial by x-coordinate
    assigned = {}
    for pred in predictions:
        pred_x = pred["x"]
        closest_label = min(fiducials, key=lambda label: abs(pred_x - fiducials[label][0]))
        if closest_label not in assigned or abs(pred_x - fiducials[closest_label][0]) < abs(assigned[closest_label]["x"] - fiducials[closest_label][0]):
            assigned[closest_label] = pred

    # Build ordered ROI entries (ROI 1 to ROI 5)
    roi_lines = []
    for idx in range(1, 6):
        label = f"ROI {idx}"
        if label in assigned:
            roi_lines.append(make_roi_entry(idx, assigned[label], cm_per_pixel) + '\n')

    with open(file_path, 'r') as f:
        lines = f.readlines()

    # Update Comment2 field
    encoding = encode_roi_positions({int(l.split()[1]): assigned[l] for l in assigned}, total_rois=5)
    lines = update_comment2(lines, encoding)

    # Find and replace the ROI section
    roi_idx = next((i for i, line in enumerate(lines) if line.startswith('*** ROIs:')), None)
    if roi_idx is None:
        raise ValueError("No '*** ROIs:' section found in file")

    roi_end = roi_idx + 1
    while roi_end < len(lines) and lines[roi_end].strip().startswith("ROI "):
        roi_end += 1
    lines = lines[:roi_idx + 1] + lines[roi_end:]
    lines = lines[:roi_idx + 1] + roi_lines + lines[roi_idx + 1:]

    with open(file_path, 'w') as f:
        f.writelines(lines)


# ---- Walk Through Subdirectories ----
def process_all_folders(base_directory, cm_fallback_policy="warn"):
    """
    Recursively find all subdirectories containing AnalyzedClickInfo.txt and photograph.TIF,
    then run ROI detection on each.
    """
    written_rois = set()

    api_key = require_api_key()

    folders = []
    for root, dirs, files in os.walk(base_directory):
        if "AnalyzedClickInfo.txt" in files and "photograph.TIF" in files:
            folders.append(root)
    folders.sort(reverse=True)

    for root in folders:
        print(f"Processing folder: {root}")
        txt_path = os.path.join(root, "AnalyzedClickInfo.txt")
        tif_path = os.path.join(root, "photograph.TIF")

        if is_saturated_click(root):
            print(f"  Skipping (saturated): {root}")
            continue

        png_path = None
        try:
            with open(txt_path, 'r') as f:
                txt_lines = f.readlines()

            cage = _return_cage(txt_lines) or "UNKNOWN"
            cm_info = get_cm_per_pixel_info(root, txt_lines)
            cm_per_pixel = cm_info["cm_per_pixel"]
            target_width = cm_info["target_width"]
            target_height = cm_info["target_height"]

            if cm_info["used_default"]:
                print(
                    "  SAFETY: cm/pixel fell back to default "
                    f"({cm_per_pixel:.12f}) for folder '{root}'."
                )
                print(f"  SAFETY: source={cm_info['source']}; evidence={cm_info['evidence']}")
                if cm_fallback_policy == "skip":
                    print("  SAFETY: skipping ROI write to prevent potential bad mapping.")
                    continue

            png_path, original_size = normalize_tif_to_png(tif_path)
            results = call_roboflow_local_image(png_path, api_key)
            predictions = normalize_predictions(
                results["predictions"],
                original_size,
                target_width,
                target_height,
            )

            # Assign predictions to fiducial ROI numbers
            fiducial_scale = target_width / REFERENCE_CANVAS_WIDTH
            fiducials = {roi_num: x * fiducial_scale for roi_num, x in REFERENCE_FIDUCIAL_X.items()}
            assigned = {}
            for pred in predictions:
                pred_x = pred["x"]
                closest_num = min(fiducials, key=lambda num: abs(pred_x - fiducials[num]))
                if closest_num not in assigned or abs(pred_x - fiducials[closest_num]) < abs(assigned[closest_num]["x"] - fiducials[closest_num]):
                    assigned[closest_num] = pred

            # Deduplicate: skip ROIs already written for this cage+position
            pos_map = {"nsg_dorsal": "D", "nsg_ventral": "V"}
            filtered_preds = []
            for roi_num in range(1, 6):
                pred = assigned.get(roi_num)
                if pred:
                    roi_pos = pos_map.get(pred.get("class", ""), "X")
                    key = (cage, roi_num, roi_pos)
                    if key not in written_rois:
                        filtered_preds.append(pred)
                        written_rois.add(key)

            insert_rois_to_file(txt_path, filtered_preds, cm_per_pixel, target_width)
            print(f"  Updated: {txt_path} ({len(filtered_preds)} ROIs written)")

        except Exception as e:
            print(f"  Error in {root}: {e}")
            traceback.print_exc()
        finally:
            if png_path and os.path.exists(png_path):
                os.remove(png_path)


# ---- CLI Entrypoint ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Detect dorsal/ventral ROIs and write ROI boxes into IVIS "
            "AnalyzedClickInfo.txt files."
        )
    )
    parser.add_argument("directory", help="Path to parent directory containing IVIS subfolders")
    parser.add_argument(
        "--cm-fallback-policy",
        choices=["warn", "skip"],
        default="warn",
        help=(
            "Safety behavior when cm/pixel inference falls back to default: "
            "'warn' writes ROI with warning, 'skip' skips writing that folder."
        ),
    )
    args = parser.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory")
        sys.exit(1)

    process_all_folders(directory, cm_fallback_policy=args.cm_fallback_policy)
