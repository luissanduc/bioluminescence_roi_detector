# Bioluminescence ROI Detector

Automatically draw ROI (Region of Interest) boxes on IVIS bioluminescence images of mice using a Roboflow object detection model. The script recursively scans a directory of IVIS Living Image output folders, detects dorsal and ventral mouse positions, and writes ROI coordinates directly back into the `AnalyzedClickInfo.txt` files.

---

## What It Does

1. Walks a directory tree looking for folders that contain `AnalyzedClickInfo.txt` and `photograph.TIF` (standard IVIS Living Image output structure).
2. Converts each 16-bit TIFF to an 8-bit PNG for API compatibility.
3. Sends the image to a pre-trained Roboflow model that detects mouse positions (`nsg_dorsal` / `nsg_ventral`).
4. Assigns each detected bounding box to one of five fiducial ROI positions based on x-coordinate proximity.
5. Writes the ROI coordinates and a position encoding (e.g. `D,V,X,X,D`) into `Comment2` of `AnalyzedClickInfo.txt`.
6. Skips images flagged as saturated.

> **Warning:** This script **overwrites** existing ROI entries and `Comment2` fields in `AnalyzedClickInfo.txt`. Back up your data before running on a dataset for the first time.

---

## Requirements

- Python 3.8 or later
- A [Roboflow](https://roboflow.com) account (free tier works)

### Install Python on macOS with Homebrew

If Python is missing or does not include GUI support in your environment:

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python

# Verify
python3 --version
pip3 --version
```

Recommended project setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Python dependencies

```bash
pip install -r requirements.txt
```

Packages used: `pillow`, `numpy`, `requests`

---

## Setup

### 1. Get a Roboflow API Key

1. Go to [https://app.roboflow.com/settings/api](https://app.roboflow.com/settings/api)
2. Create a free account if you don't have one
3. Copy your **Private API Key**

### 2. Set Your API Key

**Option A — environment variable (recommended):**

```bash
export ROBOFLOW_API_KEY="your_api_key_here"
```

Add this line to your `~/.zshrc` or `~/.bashrc` to make it permanent.

**Option B — `.env` file:**

```bash
cp .env.example .env
# Then edit .env and replace "your_api_key_here" with your actual key
```

> The `.env` file is listed in `.gitignore` and will never be committed to git.

### 3. Access the Model

The script uses a pre-trained model hosted on Roboflow Universe:

**Model:** [https://universe.roboflow.com/luissandoval/mice-hlehy](https://universe.roboflow.com/luissandoval/mice-hlehy)

This model detects two classes:
- `nsg_dorsal` — mouse imaged dorsal (back) side up
- `nsg_ventral` — mouse imaged ventral (belly) side up

You can use this model directly with your own API key — no extra setup needed. If you want to fine-tune the model on your own data or create a private copy, click **"Fork"** on the model page in Roboflow Universe.

---

## Usage

```bash
python bioluminescence_roi_detector.py /path/to/your/ivis/data
```

Optional safety mode (recommended for mixed or uncertain datasets):

```bash
python bioluminescence_roi_detector.py /path/to/your/ivis/data --cm-fallback-policy skip
```

- `--cm-fallback-policy warn` (default): prints a safety warning and still writes ROI entries.
- `--cm-fallback-policy skip`: prints the warning and skips ROI writing for that folder.

The script will recursively search `/path/to/your/ivis/data` for all subdirectories containing both `AnalyzedClickInfo.txt` and `photograph.TIF`, and process each one.

### Example

```
/data/experiment_2024/
├── mouse_01/
│   ├── AnalyzedClickInfo.txt
│   ├── photograph.TIF
│   └── ...
├── mouse_02/
│   ├── AnalyzedClickInfo.txt
│   ├── photograph.TIF
│   └── ...
```

```bash
python bioluminescence_roi_detector.py /data/experiment_2024
```

### Check inferred cm/pixel before writing ROIs

If ROI placement looks off (especially when IVIS metadata does not include an `Instrument:` field), run:

```bash
python infer_cm_per_pixel.py /path/to/your/ivis/data
```

This prints one line per folder with:

- inferred `cm_per_pixel`
- source used to infer it (`Instrument`, `System Configuration`, `metadata-text`, `existing-roi`, or `default`)
- evidence string used for the decision

Optional JSON output:

```bash
python infer_cm_per_pixel.py /path/to/your/ivis/data --json cm_report.json
```

### Run with double-click (macOS and Windows)

If you want a file-explorer workflow instead of terminal commands:

1. Double-click [run_roi_detector_mac.command](run_roi_detector_mac.command) on macOS
2. Double-click [run_roi_detector_windows.bat](run_roi_detector_windows.bat) on Windows

Both launchers open a folder picker so you can choose the parent directory to process.
The GUI always uses safety policy `skip` for cm/pixel fallback (no bad-mapping prompt).

If your Python environment does not include `tkinter` (for example `ModuleNotFoundError: No module named '_tkinter'`),
the launcher now automatically falls back to native macOS/Windows dialogs (or terminal prompts on other platforms).

You can also run the GUI directly:

```bash
python run_roi_detector_gui.py
```

---

## Configuration

Open `bioluminescence_roi_detector.py` and adjust these constants near the top of the file:

| Variable | Default | Description |
|---|---|---|
| `CONFIDENCE` | `0.80` | Minimum detection confidence threshold (0–1) |
| `IOU_THRESHOLD` | `0.5` | Overlap threshold for suppressing duplicate boxes |
| `INSTRUMENT_PROFILES` | see below | Instrument profile map with cm/pixel and target canvas size |
| `DEFAULT_INSTRUMENT` | `ivis 50` | Fallback profile when instrument metadata cannot be inferred |

**Instrument auto-detection:** The script reads the `Instrument:` field from each `AnalyzedClickInfo.txt` and looks up the correct cm/pixel value automatically. Known instruments:

When `Instrument:` is missing (common in some IVIS exports), the script also checks `System Configuration`, `Lens Type`, and full metadata text from `ClickInfo.txt`.

| Instrument | cm/pixel |
|---|---|
| IVIS 50 | `0.010253906250` |
| IVIS 200 | `0.011562500000` |

To add a new instrument, append an entry to `INSTRUMENT_PROFILES` at the top of the script:
```python
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
```
If an unrecognized instrument is encountered, the script will print a warning and fall back to `DEFAULT_INSTRUMENT`.

---

## Output

For each processed folder, the script updates `AnalyzedClickInfo.txt`:

- **ROI entries** are written under the `*** ROIs:` section with bounding box coordinates, shape, and cm-per-pixel scale.
- **Comment2** is updated with a position code:
  - `D` = dorsal detected
  - `V` = ventral detected
  - `X` = no detection for that ROI slot

Example `Comment2` value:
```
Comment2:   D,V,X,X,D
```
This means: ROI 1 = dorsal, ROI 2 = ventral, ROI 3 = no detection, ROI 4 = no detection, ROI 5 = dorsal.

---

## Troubleshooting

**`ROBOFLOW_API_KEY environment variable is not set`**
Set the variable as described in Setup → Step 2.

**`No '*** ROIs:' section found in file`**
The `AnalyzedClickInfo.txt` file is missing the expected ROI section header. Verify the file was exported from IVIS Living Image software.

**`401 Unauthorized` from Roboflow API**
Your API key is invalid or expired. Check it at [https://app.roboflow.com/settings/api](https://app.roboflow.com/settings/api).

**Saturated images are skipped**
Any folder where `AnalyzedClickInfo.txt` contains `Saturated: 1` is automatically skipped to avoid processing unreliable data.

**Using a new instrument (unknown resolution or cm/pixel)**

If ROI placement is off with a new camera system, follow this checklist:

1. **Confirm instrument identity from metadata**
  - Open `ClickInfo.txt` and look for fields like:
    - `System Configuration:`
    - `Lens Type:`
    - `Instrument:` (if present)
2. **Estimate target width/height (effective canvas)**
  - Check one raw image size first (for example with Python/Pillow).
  - If ROIs are consistently too large and shifted down-right, your target canvas is likely smaller than the value in the script.
  - For IVIS-style data, you can often infer effective width by comparing `Field of View` to known cm/pixel or by inspecting center-grid calibration lines in `ClickInfo.txt` comments.
3. **Estimate `cm_per_pixel`**
  - Preferred: use a validated value from instrument calibration docs or a previously correct ROI export.
  - Practical fallback: compute

    ```text
    cm_per_pixel = field_of_view_cm / effective_image_width_px
    ```

  - Example (IVIS200): `22.2 / 1920 = 0.0115625`.
4. **Validate before writing ROIs**
  - Run:

    ```bash
    python infer_cm_per_pixel.py /path/to/your/ivis/data
    ```

  - Confirm no unexpected `default` source in output.
5. **Add the new instrument profile in code**
  - Edit `INSTRUMENT_PROFILES` in `bioluminescence_roi_detector.py` and add:

    ```python
    "your instrument name": {
      "cm_per_pixel": <value>,
      "target_width": <value>,
      "target_height": <value>,
    }
    ```

  - Add aliases in `INSTRUMENT_ALIASES` so metadata text can match reliably.
6. **Run with safety skip enabled while testing**
  - Use:

    ```bash
    python bioluminescence_roi_detector.py /path/to/your/ivis/data --cm-fallback-policy skip
    ```

  - This prevents bad writes when metadata matching fails.

Tip: keep 2–3 representative folders from the new instrument as a regression test set and verify overlay alignment after profile changes.

---

## File Structure

```
.
├── bioluminescence_roi_detector.py   # Main script
├── requirements.txt                  # Python dependencies
├── .env.example                      # Template for your API key
├── .gitignore
└── README.md
```

---

## Citation / Acknowledgments

If you use this tool in a publication, please cite the Roboflow model:

> Sandoval, L., Zhang, S., Marsh, D. Mice bioluminescence ROI detector (mice-hlehy). Roboflow Universe. https://universe.roboflow.com/luissandoval/mice-hlehy
