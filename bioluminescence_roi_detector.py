import os
import sys
import requests
import base64
import tempfile
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
# Get API key from environment variable (never hardcode your key)
API_KEY = os.environ.get("ROBOFLOW_API_KEY")
if not API_KEY:
    print(
        "Error: ROBOFLOW_API_KEY environment variable is not set.\n"
        "Please set it before running this script:\n"
        "  export ROBOFLOW_API_KEY='your_api_key_here'\n"
        "You can get your API key at: https://app.roboflow.com/settings/api"
    )
    sys.exit(1)

# The public Roboflow model used for bioluminescence ROI detection.
# This model detects dorsal (D) and ventral (V) mouse positions.
# You can view the model at: https://universe.roboflow.com/luissandoval/mice-hlehy
# If you want to fine-tune or copy the model to your own Roboflow workspace, visit the link above.
PROJECT_ID = "mice-hlehy"
MODEL_VERSION = "8"

CONFIDENCE = 0.80
IOU_THRESHOLD = 0.5

# Pixel-to-centimeter conversion factors by instrument.
# The script reads the "Instrument:" field from AnalyzedClickInfo.txt and looks up
# the matching value automatically. Add new instruments here as needed.
INSTRUMENT_CM_PER_PIXEL = {
    "ivis 50":      0.010253906250,
    "ivis50":       0.010253906250,
    "ivis 200":     0.011562500000,
    "ivis200":      0.011562500000,
}
DEFAULT_CM_PER_PIXEL = 0.010253906250  # Fallback (IVIS 50) if instrument is not recognized

TARGET_WIDTH = 2048
TARGET_HEIGHT = 2048


# ---- Detect Instrument and Resolve cm/pixel ----
def get_cm_per_pixel(txt_lines):
    """
    Read the 'Instrument:' field from an IVIS text file and return the matching
    cm/pixel value. Falls back to DEFAULT_CM_PER_PIXEL if the instrument is unknown
    or the field is absent.
    """
    for line in txt_lines:
        if line.strip().lower().startswith("instrument:"):
            instrument = line.split(":", 1)[-1].strip()
            instrument_lower = instrument.lower()
            for key, value in INSTRUMENT_CM_PER_PIXEL.items():
                if key in instrument_lower:
                    print(f"  Instrument: {instrument} -> {value:.12f} cm/pixel")
                    return value
            print(
                f"  Warning: Unrecognized instrument '{instrument}'. "
                f"Using default {DEFAULT_CM_PER_PIXEL} cm/pixel. "
                f"Add it to INSTRUMENT_CM_PER_PIXEL in the script if needed."
            )
            return DEFAULT_CM_PER_PIXEL
    print(
        f"  Warning: No 'Instrument:' field found in file. "
        f"Using default {DEFAULT_CM_PER_PIXEL} cm/pixel."
    )
    return DEFAULT_CM_PER_PIXEL


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
def call_roboflow_local_image(image_path):
    """Send an image to the Roboflow inference API and return predictions."""
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")

    url = (
        f"https://detect.roboflow.com/{PROJECT_ID}/{MODEL_VERSION}"
        f"?api_key={API_KEY}&confidence={CONFIDENCE}&overlap={IOU_THRESHOLD}"
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
def normalize_predictions(predictions, original_size):
    """Scale bounding box coordinates from the original image size to TARGET_WIDTH x TARGET_HEIGHT."""
    orig_w, orig_h = original_size
    norm = []
    for pred in predictions:
        if pred["confidence"] < CONFIDENCE and pred.get("class", "") not in ["nsg_ventral", "nsg_dorsal"]:
            print(f"Skipping low confidence prediction: {pred}")
            continue
        scale_x = TARGET_WIDTH / orig_w
        scale_y = TARGET_HEIGHT / orig_h
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
def insert_rois_to_file(file_path, predictions, cm_per_pixel):
    """Assign predictions to fiducial ROI positions and write them to the IVIS text file."""
    # Fiducial x-coordinates for the 5 ROI positions (pixels in 2048-wide image)
    fiducials = {
        "ROI 1": (200, 850),
        "ROI 2": (600, 850),
        "ROI 3": (1000, 850),
        "ROI 4": (1400, 850),
        "ROI 5": (1800, 850)
    }

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
def process_all_folders(base_directory):
    """
    Recursively find all subdirectories containing AnalyzedClickInfo.txt and photograph.TIF,
    then run ROI detection on each.
    """
    written_rois = set()

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
            png_path, original_size = normalize_tif_to_png(tif_path)
            results = call_roboflow_local_image(png_path)
            predictions = normalize_predictions(results["predictions"], original_size)

            with open(txt_path, 'r') as f:
                txt_lines = f.readlines()

            cage = _return_cage(txt_lines) or "UNKNOWN"
            cm_per_pixel = get_cm_per_pixel(txt_lines)

            # Assign predictions to fiducial ROI numbers
            fiducials = {1: 200, 2: 600, 3: 1000, 4: 1400, 5: 1800}
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

            insert_rois_to_file(txt_path, filtered_preds, cm_per_pixel)
            print(f"  Updated: {txt_path} ({len(filtered_preds)} ROIs written)")

        except Exception as e:
            print(f"  Error in {root}: {e}")
            traceback.print_exc()
        finally:
            if png_path and os.path.exists(png_path):
                os.remove(png_path)


# ---- CLI Entrypoint ----
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bioluminescence_roi_detector.py /path/to/parent_directory")
        sys.exit(1)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory")
        sys.exit(1)

    process_all_folders(directory)
