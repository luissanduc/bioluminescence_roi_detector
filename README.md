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

### Python dependencies

```bash
pip install -r requirements.txt
```

Packages used: `Pillow`, `numpy`, `requests`

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

---

## Configuration

Open `bioluminescence_roi_detector.py` and adjust these constants near the top of the file:

| Variable | Default | Description |
|---|---|---|
| `CONFIDENCE` | `0.80` | Minimum detection confidence threshold (0–1) |
| `IOU_THRESHOLD` | `0.5` | Overlap threshold for suppressing duplicate boxes |
| `INSTRUMENT_CM_PER_PIXEL` | see below | Lookup table mapping instrument names to cm/pixel |
| `DEFAULT_CM_PER_PIXEL` | `0.010253906250` | Fallback if instrument is not in the table |
| `TARGET_WIDTH` | `2048` | Expected image width after normalization |
| `TARGET_HEIGHT` | `2048` | Expected image height after normalization |

**Instrument auto-detection:** The script reads the `Instrument:` field from each `AnalyzedClickInfo.txt` and looks up the correct cm/pixel value automatically. Known instruments:

| Instrument | cm/pixel |
|---|---|
| IVIS 50 | `0.010253906250` |
| IVIS 200 | `0.011562500000` |

To add a new instrument, append an entry to `INSTRUMENT_CM_PER_PIXEL` at the top of the script:
```python
INSTRUMENT_CM_PER_PIXEL = {
    "ivis 50":  0.010253906250,
    "ivis 200": 0.011562500000,
    "ivis spectrum": 0.0XXXXXXXXX,  # add your value here
}
```
If an unrecognized instrument is encountered, the script will print a warning and fall back to `DEFAULT_CM_PER_PIXEL`.

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
