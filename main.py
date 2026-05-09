#!/usr/bin/env python3
"""
IQ-converter to SIGMF by Sudama
Converts raw .iq files to SigMF format (.sigmf-data + .sigmf-meta).
Optimised for large files (2–6+ GB) using chunked streaming I/O.
"""

import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Constants & dtype catalogue
# ─────────────────────────────────────────────────────────────────────────────

APP_TITLE   = "IQ-converter to SIGMF by Sudama"
CONFIG_PATH = Path.home() / ".iq_converter_config.json"

# 64 MB of raw input bytes per streaming pass (safe for any RAM)
CHUNK_BYTES = 64 * 1024 * 1024

# dtype_key → (numpy dtype string, bytes/complex-sample, IQ offset, IQ divisor)
DTYPE_INFO: dict[str, tuple[str, int, float, float]] = {
    "cu8  — Complex Uint8  (RTL-SDR)           — 2 B/sample":
        ("uint8", 2, 127.5, 127.5),
    "ci8  — Complex Int8   (HackRF/BladeRF)    — 2 B/sample":
        ("int8",  2, 0.0,   128.0),
    "ci16 — Complex Int16 LE                   — 4 B/sample":
        ("<i2",   4, 0.0,   32768.0),
    "ci16 — Complex Int16 BE                   — 4 B/sample":
        (">i2",   4, 0.0,   32768.0),
    "cf32 — Complex Float32 LE (GNU Radio)     — 8 B/sample":
        ("<f4",   8, 0.0,   1.0),
    "cf32 — Complex Float32 BE                 — 8 B/sample":
        (">f4",   8, 0.0,   1.0),
    "cf64 — Complex Float64 LE                 — 16 B/sample":
        ("<f8",  16, 0.0,   1.0),
}

# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def fmt_bytes(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_eta(secs: float) -> str:
    if secs <= 0 or not math.isfinite(secs):
        return "–"
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_speed(bps: float) -> str:
    mb = bps / 1_048_576
    return f"{mb / 1024:.1f} GB/s" if mb >= 1024 else f"{mb:.1f} MB/s"


def load_cfg() -> dict:
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open() as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_cfg(cfg: dict) -> None:
    try:
        with CONFIG_PATH.open("w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Core conversion logic — runs in a background thread
# ─────────────────────────────────────────────────────────────────────────────

def convert_iq_to_sigmf(
    input_path:  str,
    output_dir:  str,
    dtype_key:   str,
    sample_rate: float,
    center_freq: float,
    description: str,
    progress_cb,               # callable(pct, speed_bps, eta_s, done_b, total_b)
    cancel_evt:  threading.Event,
) -> tuple[bool, str]:
    """Stream-convert .iq → .sigmf-data (cf32_le) + .sigmf-meta."""

    np_dtype_str, bps, offset, scale = DTYPE_INFO[dtype_key]
    np_dtype  = np.dtype(np_dtype_str)
    file_size = os.path.getsize(input_path)

    if file_size == 0:
        return False, "Input file is empty."

    total_bytes = (file_size // bps) * bps  # trim to aligned boundary
    stem      = Path(input_path).stem
    out_dir   = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_out  = out_dir / f"{stem}.sigmf-data"
    meta_out  = out_dir / f"{stem}.sigmf-meta"

    sigmf_meta = {
        "global": {
            "core:datatype":    "cf32_le",
            "core:sample_rate": sample_rate,
            "core:version":     "1.0.0",
            "core:description": description,
            "core:author":      APP_TITLE,
        },
        "captures": [
            {"core:sample_start": 0, "core:frequency": center_freq}
        ],
        "annotations": [],
    }

    done_bytes   = 0
    t0           = time.monotonic()
    speed_window: deque[tuple[float, int]] = deque(maxlen=20)
    speed_window.append((t0, 0))

    try:
        with open(input_path, "rb") as fin, open(data_out, "wb") as fout:
            while done_bytes < total_bytes:
                if cancel_evt.is_set():
                    fout.close()
                    try:
                        data_out.unlink()
                    except Exception:
                        pass
                    return False, "Conversion cancelled."

                want = min(CHUNK_BYTES, total_bytes - done_bytes)
                want = (want // bps) * bps  # keep alignment
                if want == 0:
                    break

                raw = fin.read(want)
                if not raw:
                    break

                # Trim trailing partial sample if read was short
                rem = len(raw) % bps
                if rem:
                    raw = raw[:-rem]
                if not raw:
                    break

                arr    = np.frombuffer(raw, dtype=np_dtype)
                i_part = arr[0::2].astype(np.float32)
                q_part = arr[1::2].astype(np.float32)

                if offset != 0.0:
                    i_part -= offset
                    q_part -= offset
                if scale != 1.0:
                    i_part /= scale
                    q_part /= scale

                out = (i_part + 1j * q_part).astype(np.complex64)
                out.tofile(fout)

                done_bytes += len(raw)
                now = time.monotonic()
                speed_window.append((now, done_bytes))

                dt    = now - speed_window[0][0]
                db    = done_bytes - speed_window[0][1]
                speed = db / dt if dt > 0 else 0.0
                eta   = (total_bytes - done_bytes) / speed if speed > 0 else 0.0
                pct   = done_bytes / total_bytes * 100.0
                progress_cb(pct, speed, eta, done_bytes, total_bytes)

    except Exception as exc:
        return False, f"Conversion error: {exc}"

    try:
        with meta_out.open("w") as f:
            json.dump(sigmf_meta, f, indent=2)
    except Exception as exc:
        return False, f"Failed to write metadata: {exc}"

    elapsed   = time.monotonic() - t0
    avg_speed = total_bytes / elapsed if elapsed > 0 else 0.0
    return True, (
        f"Done in {fmt_eta(elapsed)}  (avg {fmt_speed(avg_speed)})\n\n"
        f"  Data : {data_out}\n"
        f"  Meta : {meta_out}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUI  (Catppuccin Mocha palette)
# ─────────────────────────────────────────────────────────────────────────────

C_BASE    = "#1e1e2e"
C_MANTLE  = "#181825"
C_SURFACE = "#313244"
C_OVERLAY = "#45475a"
C_TEXT    = "#cdd6f4"
C_SUBTEXT = "#a6adc8"
C_BLUE    = "#89b4fa"
C_CYAN    = "#89dceb"
C_GREEN   = "#a6e3a1"
C_RED     = "#f38ba8"
C_YELLOW  = "#f9e2af"
C_MAUVE   = "#cba6f7"


class IQConverterApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=C_BASE)
        self.root.resizable(False, False)
        self._set_icon()

        self.cfg         = load_cfg()
        self._cancel_evt = threading.Event()
        self._converting = False

        self._setup_styles()
        self._build_ui()
        self._apply_config()

    # ── Icon ──────────────────────────────────────────────────────────────

    def _set_icon(self):
        ico = Path(__file__).parent / "icon.ico"
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

    # ── ttk theme ─────────────────────────────────────────────────────────

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure(".", background=C_BASE, foreground=C_TEXT,
                    font=("Segoe UI", 10), borderwidth=0)
        s.configure("TFrame",     background=C_BASE)
        s.configure("TLabel",     background=C_BASE, foreground=C_TEXT)
        s.configure("TSeparator", background=C_OVERLAY)
        s.configure("TEntry",
                    fieldbackground=C_SURFACE, foreground=C_TEXT,
                    insertcolor=C_TEXT,
                    bordercolor=C_OVERLAY, lightcolor=C_OVERLAY, darkcolor=C_OVERLAY)
        s.configure("TCombobox",
                    fieldbackground=C_SURFACE, foreground=C_TEXT,
                    selectbackground=C_BLUE, selectforeground=C_BASE,
                    arrowcolor=C_TEXT, bordercolor=C_OVERLAY)
        s.map("TCombobox",
              fieldbackground=[("readonly", C_SURFACE)],
              foreground=[("readonly", C_TEXT)])
        s.configure("TCheckbutton",
                    background=C_BASE, foreground=C_SUBTEXT,
                    indicatorcolor=C_SURFACE)
        s.map("TCheckbutton",
              foreground=[("active", C_TEXT)],
              indicatorcolor=[("selected", C_BLUE)])
        s.configure("TLabelframe",
                    background=C_BASE, bordercolor=C_OVERLAY, relief="flat")
        s.configure("TLabelframe.Label",
                    background=C_BASE, foreground=C_BLUE,
                    font=("Segoe UI", 10, "bold"))
        s.configure("Accent.TButton",
                    background=C_BLUE, foreground=C_BASE,
                    font=("Segoe UI", 10, "bold"), padding=(18, 7))
        s.map("Accent.TButton",
              background=[("active", C_MAUVE), ("disabled", C_OVERLAY)],
              foreground=[("disabled", C_SUBTEXT)])
        s.configure("Neutral.TButton",
                    background=C_SURFACE, foreground=C_TEXT,
                    font=("Segoe UI", 10), padding=(12, 5))
        s.map("Neutral.TButton",
              background=[("active", C_OVERLAY)])
        s.configure("Cancel.TButton",
                    background=C_SURFACE, foreground=C_TEXT,
                    font=("Segoe UI", 10), padding=(18, 7))
        s.map("Cancel.TButton",
              background=[("active", C_RED), ("disabled", C_OVERLAY)],
              foreground=[("active", C_BASE), ("disabled", C_SUBTEXT)])
        s.configure("Wave.Horizontal.TProgressbar",
                    troughcolor=C_SURFACE, background=C_GREEN,
                    bordercolor=C_SURFACE, lightcolor=C_GREEN,
                    darkcolor=C_GREEN, thickness=20)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = self.root

        # Title bar
        hdr = tk.Frame(root, bg=C_MANTLE)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="⚡  " + APP_TITLE,
            bg=C_MANTLE, fg=C_BLUE,
            font=("Segoe UI", 13, "bold"),
            padx=16, pady=11,
        ).pack(side="left")

        # Body
        body = tk.Frame(root, bg=C_BASE)
        body.pack(fill="both", expand=True, padx=20, pady=14)

        def sep():
            tk.Frame(body, bg=C_OVERLAY, height=1).pack(fill="x", pady=5)

        def section(title, builder):
            f = ttk.LabelFrame(body, text=title, padding=(12, 8))
            f.pack(fill="x", pady=(0, 2))
            builder(f)

        section("Input File",    self._s_input)
        sep()
        section("IQ Format",     self._s_format)
        sep()
        section("Output Folder", self._s_output)
        sep()
        section("Progress",      self._s_progress)

        self._build_buttons(body)

    # ── Section: Input ────────────────────────────────────────────────────

    def _s_input(self, f: tk.Widget):
        row = tk.Frame(f, bg=C_BASE)
        row.pack(fill="x")
        self._input_var = tk.StringVar()
        e = ttk.Entry(row, textvariable=self._input_var, width=56)
        e.pack(side="left", fill="x", expand=True, ipady=5)
        e.bind("<FocusOut>", lambda _: self._refresh_info())
        e.bind("<Return>",   lambda _: self._refresh_info())
        ttk.Button(row, text="Browse…", command=self._browse_input,
                   style="Neutral.TButton").pack(side="left", padx=(8, 0))

        info = tk.Frame(f, bg=C_BASE)
        info.pack(fill="x", pady=(5, 0))
        self._info_var = tk.StringVar(value="No file selected")
        tk.Label(info, textvariable=self._info_var,
                 bg=C_BASE, fg=C_SUBTEXT, font=("Segoe UI", 9)).pack(side="left")

    # ── Section: Format ───────────────────────────────────────────────────

    def _s_format(self, f: tk.Widget):
        # Data type
        r1 = tk.Frame(f, bg=C_BASE)
        r1.pack(fill="x", pady=(0, 7))
        tk.Label(r1, text="Data type:", bg=C_BASE, fg=C_SUBTEXT,
                 width=13, anchor="w").pack(side="left")
        self._dtype_var = tk.StringVar()
        cb = ttk.Combobox(r1, textvariable=self._dtype_var,
                          values=list(DTYPE_INFO.keys()),
                          state="readonly", width=54)
        cb.pack(side="left", ipady=4)
        cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_info())

        # Sample rate + centre frequency
        r2 = tk.Frame(f, bg=C_BASE)
        r2.pack(fill="x", pady=(0, 7))
        tk.Label(r2, text="Sample rate:", bg=C_BASE, fg=C_SUBTEXT,
                 width=13, anchor="w").pack(side="left")
        self._srate_var = tk.StringVar(value="2.048")
        ttk.Entry(r2, textvariable=self._srate_var, width=12).pack(side="left", ipady=5)
        tk.Label(r2, text="MHz", bg=C_BASE, fg=C_SUBTEXT).pack(side="left", padx=(4, 24))
        tk.Label(r2, text="Centre freq:", bg=C_BASE, fg=C_SUBTEXT,
                 width=13, anchor="w").pack(side="left")
        self._freq_var = tk.StringVar(value="0.0")
        ttk.Entry(r2, textvariable=self._freq_var, width=12).pack(side="left", ipady=5)
        tk.Label(r2, text="MHz", bg=C_BASE, fg=C_SUBTEXT).pack(side="left", padx=(4, 0))

        # Description
        r3 = tk.Frame(f, bg=C_BASE)
        r3.pack(fill="x")
        tk.Label(r3, text="Description:", bg=C_BASE, fg=C_SUBTEXT,
                 width=13, anchor="w").pack(side="left")
        self._desc_var = tk.StringVar()
        ttk.Entry(r3, textvariable=self._desc_var, width=48).pack(side="left", ipady=5)

    # ── Section: Output ───────────────────────────────────────────────────

    def _s_output(self, f: tk.Widget):
        row = tk.Frame(f, bg=C_BASE)
        row.pack(fill="x")
        self._outdir_var = tk.StringVar()
        ttk.Entry(row, textvariable=self._outdir_var, width=56).pack(
            side="left", fill="x", expand=True, ipady=5)
        ttk.Button(row, text="Browse…", command=self._browse_output,
                   style="Neutral.TButton").pack(side="left", padx=(8, 0))

        self._remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Remember this folder",
                        variable=self._remember_var).pack(anchor="w", pady=(8, 0))

    # ── Section: Progress ─────────────────────────────────────────────────

    def _s_progress(self, f: tk.Widget):
        self._pbar_var = tk.DoubleVar(value=0.0)
        pbar = ttk.Progressbar(f, variable=self._pbar_var, maximum=100,
                               style="Wave.Horizontal.TProgressbar", length=620)
        pbar.pack(fill="x", pady=(0, 8))

        stats = tk.Frame(f, bg=C_BASE)
        stats.pack(fill="x")

        def stat(parent, label, var, fg):
            tk.Label(parent, text=label, bg=C_BASE, fg=C_SUBTEXT,
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Label(parent, textvariable=var, bg=C_BASE, fg=fg,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=(2, 18))

        self._pct_var   = tk.StringVar(value="0 %")
        self._speed_var = tk.StringVar(value="–")
        self._eta_var   = tk.StringVar(value="–")
        stat(stats, "Progress:", self._pct_var,   C_GREEN)
        stat(stats, "Speed:",    self._speed_var,  C_CYAN)
        stat(stats, "ETA:",      self._eta_var,    C_YELLOW)

        sz_row = tk.Frame(f, bg=C_BASE)
        sz_row.pack(fill="x", pady=(5, 0))
        self._written_var = tk.StringVar(value="0 B / –")
        stat(sz_row, "Written:", self._written_var, C_TEXT)

        self._status_var = tk.StringVar(value="Idle — select a file and click Convert")
        tk.Label(f, textvariable=self._status_var,
                 bg=C_BASE, fg=C_SUBTEXT, font=("Segoe UI", 9, "italic"),
                 wraplength=600, justify="left").pack(anchor="w", pady=(8, 0))

    # ── Buttons ───────────────────────────────────────────────────────────

    def _build_buttons(self, parent: tk.Widget):
        row = tk.Frame(parent, bg=C_BASE)
        row.pack(pady=(12, 2))
        self._btn_go = ttk.Button(row, text="▶  Convert",
                                  style="Accent.TButton",
                                  command=self._start)
        self._btn_go.pack(side="left", padx=(0, 12))
        self._btn_cancel = ttk.Button(row, text="✕  Cancel",
                                      style="Cancel.TButton",
                                      command=self._cancel,
                                      state="disabled")
        self._btn_cancel.pack(side="left")

    # ── Config ────────────────────────────────────────────────────────────

    def _apply_config(self):
        keys = list(DTYPE_INFO.keys())
        default_dtype = keys[4]  # cf32 LE (GNU Radio)
        saved = self.cfg.get("dtype", default_dtype)
        self._dtype_var.set(saved if saved in keys else default_dtype)

        if self.cfg.get("remember_folder") and self.cfg.get("output_dir"):
            self._outdir_var.set(self.cfg["output_dir"])
        self._remember_var.set(self.cfg.get("remember_folder", True))
        self._srate_var.set(str(self.cfg.get("sample_rate_mhz", "2.048")))
        self._freq_var.set(str(self.cfg.get("center_freq_mhz", "0.0")))

    def _persist_config(self):
        self.cfg["dtype"]            = self._dtype_var.get()
        self.cfg["sample_rate_mhz"] = self._srate_var.get()
        self.cfg["center_freq_mhz"] = self._freq_var.get()
        self.cfg["remember_folder"] = self._remember_var.get()
        if self._remember_var.get():
            self.cfg["output_dir"] = self._outdir_var.get()
        save_cfg(self.cfg)

    # ── File browsing ─────────────────────────────────────────────────────

    def _browse_input(self):
        p = filedialog.askopenfilename(
            title="Select IQ file",
            filetypes=[("IQ files", "*.iq"), ("All files", "*.*")],
        )
        if not p:
            return
        self._input_var.set(p)
        self._refresh_info()
        if not self._outdir_var.get():
            self._outdir_var.set(str(Path(p).parent))

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self._outdir_var.set(d)

    def _refresh_info(self):
        p = self._input_var.get().strip()
        if not p or not os.path.isfile(p):
            self._info_var.set("No file selected")
            return
        size = os.path.getsize(p)
        dk   = self._dtype_var.get()
        if dk in DTYPE_INFO:
            bps   = DTYPE_INFO[dk][1]
            n_smp = size // bps
            out_b = n_smp * 8  # cf32 = 8 bytes/sample
            self._info_var.set(
                f"Size: {fmt_bytes(size)}   |   "
                f"Samples: {n_smp:,}   |   "
                f"Output: ~{fmt_bytes(out_b)}"
            )
        else:
            self._info_var.set(f"Size: {fmt_bytes(size)}")

    # ── Validation ────────────────────────────────────────────────────────

    def _validate(self) -> tuple[bool, str]:
        p = self._input_var.get().strip()
        if not p:
            return False, "Please select an input .iq file."
        if not os.path.isfile(p):
            return False, f"File not found:\n{p}"
        if self._dtype_var.get() not in DTYPE_INFO:
            return False, "Please select a data type."
        d = self._outdir_var.get().strip()
        if not d:
            return False, "Please select an output folder."
        try:
            v = float(self._srate_var.get())
            if v <= 0:
                raise ValueError
        except ValueError:
            return False, "Sample rate must be a positive number (MHz)."
        try:
            float(self._freq_var.get())
        except ValueError:
            return False, "Centre frequency must be a number (MHz)."
        return True, ""

    # ── Conversion orchestration ──────────────────────────────────────────

    def _start(self):
        ok, msg = self._validate()
        if not ok:
            messagebox.showerror("Input error", msg, parent=self.root)
            return

        self._cancel_evt.clear()
        self._converting = True
        self._btn_go.config(state="disabled")
        self._btn_cancel.config(state="normal")
        self._pbar_var.set(0)
        self._pct_var.set("0 %")
        self._speed_var.set("–")
        self._eta_var.set("–")
        self._written_var.set("0 B / –")
        self._status_var.set("Starting…")
        self._persist_config()

        kw = dict(
            input_path  = self._input_var.get().strip(),
            output_dir  = self._outdir_var.get().strip(),
            dtype_key   = self._dtype_var.get(),
            sample_rate = float(self._srate_var.get()) * 1_000_000,
            center_freq = float(self._freq_var.get()) * 1_000_000,
            description = self._desc_var.get().strip(),
            progress_cb = self._on_progress,
            cancel_evt  = self._cancel_evt,
        )
        threading.Thread(target=self._run, kwargs=kw, daemon=True).start()

    def _run(self, **kw):
        ok, msg = convert_iq_to_sigmf(**kw)
        self.root.after(0, self._on_done, ok, msg)

    def _cancel(self):
        if self._converting:
            self._cancel_evt.set()
            self._status_var.set("Cancelling…")
            self._btn_cancel.config(state="disabled")

    # ── Thread → GUI callbacks ────────────────────────────────────────────

    def _on_progress(self, pct, speed, eta, done_b, total_b):
        def _up():
            self._pbar_var.set(pct)
            self._pct_var.set(f"{pct:.1f} %")
            self._speed_var.set(fmt_speed(speed))
            self._eta_var.set(fmt_eta(eta))
            self._written_var.set(f"{fmt_bytes(done_b)} / {fmt_bytes(total_b)}")
            self._status_var.set(
                f"Converting…  {pct:.1f}%  —  "
                f"{fmt_bytes(done_b)} of {fmt_bytes(total_b)}"
            )
        self.root.after(0, _up)

    def _on_done(self, ok: bool, msg: str):
        self._converting = False
        self._btn_go.config(state="normal")
        self._btn_cancel.config(state="disabled")
        if ok:
            self._pbar_var.set(100)
            self._pct_var.set("100 %")
            self._eta_var.set("Done")
            self._status_var.set("✓  Conversion complete")
            messagebox.showinfo("Complete", msg, parent=self.root)
        else:
            self._status_var.set(f"✗  {msg}")
            if "cancel" not in msg.lower():
                messagebox.showerror("Error", msg, parent=self.root)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.minsize(700, 560)
    IQConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
