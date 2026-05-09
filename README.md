# IQ-converter to SIGMF by Sudama

A fast, GUI-based tool that converts raw `.iq` files to the open
**SigMF** format (`.sigmf-data` + `.sigmf-meta`).

Built for large captures — handles 2–6 GB files and beyond using
streaming chunk I/O (constant ~130 MB RAM regardless of file size).

---

## Screenshot layout

```
╔══════════════════════════════════════════════════════════════════╗
║  ⚡  IQ-converter to SIGMF by Sudama                           ║
╠══════════════════════════════════════════════════════════════════╣
║ Input File                                                       ║
║  [path/to/capture.iq________________________]  [Browse…]        ║
║  Size: 2.4 GB  |  Samples: 300 000 000  |  Output: ~2.2 GB     ║
╠══════════════════════════════════════════════════════════════════╣
║ IQ Format                                                        ║
║  Data type:  [cf32 — Complex Float32 LE (GNU Radio) ▼]         ║
║  Sample rate: [2.048] MHz    Centre freq: [433.920] MHz         ║
║  Description: [optional free text________________________]      ║
╠══════════════════════════════════════════════════════════════════╣
║ Output Folder                                                    ║
║  [C:\Users\...\output_______________________]  [Browse…]        ║
║  ☑ Remember this folder                                         ║
╠══════════════════════════════════════════════════════════════════╣
║ Progress                                                         ║
║  [██████████████████████████████████░░░░░░]                     ║
║  Progress: 82.4 %   Speed: 412 MB/s   ETA: 3s                  ║
║  Written: 1.97 GB / 2.40 GB                                     ║
║  Converting…  82.4% — 1.97 GB of 2.40 GB                       ║
╠══════════════════════════════════════════════════════════════════╣
║           [▶  Convert]   [✕  Cancel]                           ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Features

| Feature | Detail |
|---|---|
| Supported input formats | `cu8`, `ci8`, `ci16_le/be`, `cf32_le/be`, `cf64_le` |
| Output format | Always `cf32_le` (SigMF standard) |
| Large file support | 64 MB streaming chunks — RAM usage stays constant |
| Live progress | Bar + % + MB/s throughput + rolling ETA |
| Persistent settings | Remembers output folder, data type, sample rate, freq |
| Cancel | Abort at any time — partial output is cleaned up |
| Executable | Single `.exe`, no Python needed on target machine |

---

## Supported input formats

| Label | dtype | Bytes/sample | Notes |
|---|---|---|---|
| `cu8` | `uint8` | 2 | RTL-SDR — unsigned, bias = 127.5 |
| `ci8` | `int8` | 2 | HackRF, BladeRF |
| `ci16 LE` | `int16` little-endian | 4 | LimeSDR, USRP |
| `ci16 BE` | `int16` big-endian | 4 | Some legacy hardware |
| `cf32 LE` | `float32` little-endian | 8 | **GNU Radio default** |
| `cf32 BE` | `float32` big-endian | 8 | Rare big-endian hosts |
| `cf64 LE` | `float64` little-endian | 16 | High-precision captures |

---

## Quick start — run from source

### Requirements

- Python 3.10+
- `pip install -r requirements.txt`

### Launch

```bat
cd iq_converter
python main.py
```

---

## Build the Windows `.exe`

Double-click **`build.bat`** (or run it from a terminal):

```bat
cd iq_converter
build.bat
```

The script:
1. Upgrades pip and installs `numpy`, `Pillow`, `pyinstaller`
2. Generates `icon.ico` (wave + IQ logo) via `create_icon.py`
3. Bundles everything into `dist\IQ-Converter-SIGMF.exe`

The resulting `.exe` is fully self-contained — no Python installation
needed on the target machine.

> **Note:** Some antivirus products flag PyInstaller bundles as suspicious.
> Add an exclusion for the `dist\` folder or sign the binary if needed.

---

## Step-by-step usage

1. **Browse…** → select your `.iq` file.
   - The status bar immediately shows file size, estimated sample count,
     and expected output size.

2. **Data type** → choose the format that matches your SDR software:
   - GNU Radio → `cf32 LE`
   - RTL-SDR → `cu8`
   - HackRF → `ci8`
   - LimeSDR / USRP → `ci16 LE`

3. **Sample rate** and **Centre freq** in MHz.
   - Stored in the SigMF metadata; they do not affect the samples themselves.

4. **Description** (optional free text) → written into `core:description`.

5. **Output Folder** → choose where the two output files go.
   - Tick **Remember this folder** to skip this step next time.

6. **▶ Convert** → conversion starts in a background thread; the UI stays responsive.
   - Progress bar, speed, and ETA update continuously.
   - Click **✕ Cancel** at any time to abort cleanly (partial `.sigmf-data` deleted).

7. When done, a dialog shows the full paths:
   - `<stem>.sigmf-data` — binary IQ samples (`cf32_le`)
   - `<stem>.sigmf-meta` — SigMF 1.0.0 JSON metadata

---

## Output format

### `.sigmf-data`

Binary file — interleaved `float32` little-endian I/Q samples:

```
[I₀ Q₀ I₁ Q₁ … Iₙ Qₙ]
```

### `.sigmf-meta`

```json
{
  "global": {
    "core:datatype":    "cf32_le",
    "core:sample_rate": 2048000.0,
    "core:version":     "1.0.0",
    "core:description": "example capture",
    "core:author":      "IQ-converter to SIGMF by Sudama"
  },
  "captures": [
    { "core:sample_start": 0, "core:frequency": 433920000.0 }
  ],
  "annotations": []
}
```

---

## Performance

Throughput is limited primarily by disk I/O.

| Storage | Typical speed |
|---|---|
| NVMe SSD | 500 – 1 500 MB/s |
| SATA SSD | 200 – 500 MB/s |
| HDD | 80 – 180 MB/s |

RAM usage is constant at ~130 MB regardless of file size.

---

## Project structure

```
iq_converter/
├── main.py           ← GUI application (entry point)
├── create_icon.py    ← Generates icon.ico (wave + IQ logo) using Pillow
├── icon.ico          ← Application icon (created by build.bat)
├── requirements.txt  ← Python dependencies
├── build.bat         ← One-click Windows build → dist\IQ-Converter-SIGMF.exe
└── README.md         ← This file
```

---

## Settings persistence

User preferences are saved to `~/.iq_converter_config.json`:

```json
{
  "dtype":            "cf32 — Complex Float32 LE (GNU Radio) — 8 B/sample",
  "sample_rate_mhz":  "2.048",
  "center_freq_mhz":  "433.92",
  "remember_folder":  true,
  "output_dir":       "C:/Users/user/captures/converted"
}
```

Delete this file to reset all settings to defaults.

---

## License

MIT — by Sudama
