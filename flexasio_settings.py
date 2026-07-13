#!/usr/bin/env python3
"""FlexASIO Settings — simple driver configuration panel."""

import ctypes
import re
import subprocess
import sys
import customtkinter as ctk
from pathlib import Path

# ── single instance ───────────────────────────────────────────────────────────

_MUTEX_NAME = "FlexASIOGUI_SingleInstance"

def _ensure_single_instance():
    """If already running, focus the existing window and exit."""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = ctypes.windll.user32.FindWindowW(None, "FlexASIO")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)       # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    return mutex  # keep reference alive so mutex isn't released

CONFIG_PATH    = Path.home() / "FlexASIO.toml"
PORT_AUDIO_EXE = Path(r"C:\Program Files\FlexASIO\x64\PortAudioDevices.exe")

BACKENDS     = ["Windows WASAPI", "Windows DirectSound", "Windows WDM-KS", "MME"]
BUFFER_SIZES = [128, 256, 512, 1024, 2048]

# ── device enumeration via PortAudioDevices.exe ───────────────────────────────

def _parse_port_audio_devices():
    """Run PortAudioDevices.exe and return list of device dicts."""
    result = subprocess.run(
        [str(PORT_AUDIO_EXE)],
        capture_output=True, text=True, timeout=10,
    )
    output = result.stdout + result.stderr  # it logs to stderr
    devices, current = [], {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Device index:"):
            if current:
                devices.append(current)
            current = {}
        elif line.startswith("Device name:"):
            m = re.search(r'"([^"]*)"', line)
            current["name"] = m.group(1) if m else ""
        elif line.startswith("Host API name:"):
            current["host_api"] = line.split(":", 1)[1].strip()
        elif line.startswith("Input:") and "max channel count" in line:
            m = re.search(r"max channel count (\d+)", line)
            current["inputs"] = int(m.group(1)) if m else 0
        elif line.startswith("Output:") and "max channel count" in line:
            m = re.search(r"max channel count (\d+)", line)
            current["outputs"] = int(m.group(1)) if m else 0
    if current:
        devices.append(current)
    return devices


_device_cache = None

def get_devices(backend):
    """Return ([input names], [output names]) for the given backend."""
    global _device_cache
    try:
        if _device_cache is None:
            _device_cache = _parse_port_audio_devices()

        inputs  = ["[ Default input ]",  "[ Disabled ]"]
        outputs = ["[ Default output ]", "[ Disabled ]"]
        for dev in _device_cache:
            if dev.get("host_api", "") != backend:
                continue
            name = dev.get("name", "")
            if not name or "[Loopback]" in name:
                continue
            if dev.get("inputs",  0) > 0: inputs.append(name)
            if dev.get("outputs", 0) > 0: outputs.append(name)
        return inputs, outputs
    except Exception:
        return ["[ Default input ]", "[ Disabled ]"], ["[ Default output ]", "[ Disabled ]"]

# ── TOML read / write ─────────────────────────────────────────────────────────

def read_config():
    defaults = {
        "backend":           "Windows WASAPI",
        "bufferSizeSamples": 256,
        "input_device":      "[ Default input ]",
        "output_device":     "[ Default output ]",
        "exclusive":         True,
    }
    if not CONFIG_PATH.exists():
        return defaults

    text = CONFIG_PATH.read_text(encoding="utf-8")

    def g(pattern, text, cast=str, default=None):
        m = re.search(pattern, text, re.MULTILINE)
        return cast(m.group(1)) if m else default

    cfg = dict(defaults)
    cfg["backend"]           = g(r'^backend\s*=\s*"([^"]*)"', text) or defaults["backend"]
    cfg["bufferSizeSamples"] = g(r'^bufferSizeSamples\s*=\s*(\d+)', text, int) or defaults["bufferSizeSamples"]

    in_sec  = re.search(r'\[input\](.*?)(?=\n\[|\Z)',  text, re.DOTALL)
    out_sec = re.search(r'\[output\](.*?)(?=\n\[|\Z)', text, re.DOTALL)

    if in_sec:
        m = re.search(r'^device\s*=\s*"([^"]*)"', in_sec.group(1), re.MULTILINE)
        if m:
            cfg["input_device"] = m.group(1) if m.group(1) else "[ Disabled ]"

    if out_sec:
        m = re.search(r'^device\s*=\s*"([^"]*)"', out_sec.group(1), re.MULTILINE)
        if m:
            cfg["output_device"] = m.group(1) if m.group(1) else "[ Disabled ]"

    m = re.search(r'wasapiExclusiveMode\s*=\s*(true|false)', text)
    if m:
        cfg["exclusive"] = m.group(1) == "true"

    return cfg


def write_config(backend, buffer_size, input_device, output_device, exclusive):
    is_wasapi = backend == "Windows WASAPI"

    def device_line(name):
        if name == "[ Default input ]" or name == "[ Default output ]":
            return ""
        if name == "[ Disabled ]":
            return 'device = ""\n'
        return f'device = "{name}"\n'

    def section(label, device_name):
        lines = f"[{label}]\n"
        lines += device_line(device_name)
        if is_wasapi:
            lines += f'wasapiExclusiveMode = {"true" if exclusive else "false"}\n'
            if exclusive:
                lines += "suggestedLatencySeconds = 0.0\n"
        return lines

    body = (
        f'backend = "{backend}"\n'
        f"bufferSizeSamples = {buffer_size}\n"
        "\n"
        + section("input",  input_device)
        + "\n"
        + section("output", output_device)
    )
    CONFIG_PATH.write_text(body, encoding="utf-8")

# ── UI ────────────────────────────────────────────────────────────────────────

BG        = "#1e1e1e"
SURFACE   = "#2a2a2a"
BORDER    = "#3a3a3a"
ACCENT    = "#0078d4"
TEXT      = "#e8e8e8"
MUTED     = "#888888"
SUCCESS   = "#4ec94e"

class FlexASIOPanel(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title("FlexASIO")
        self.geometry("360x400")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        cfg = read_config()
        self._build(cfg)

    # ── layout ──────────────────────────────────────────────────────────────

    def _build(self, cfg):
        self._section_label("Backend", top=18)
        self.backend_var = ctk.StringVar(value=cfg["backend"])
        ctk.CTkOptionMenu(
            self, values=BACKENDS, variable=self.backend_var,
            command=self._on_backend_change,
            width=320, height=32,
            fg_color=SURFACE, button_color=BORDER, button_hover_color=ACCENT,
            dropdown_fg_color=SURFACE, text_color=TEXT,
        ).pack(padx=20, pady=(4, 0))

        self._section_label("Buffer Size")
        self._buf_str_var = ctk.StringVar(value=str(cfg["bufferSizeSamples"]))
        ctk.CTkSegmentedButton(
            self, values=[str(s) for s in BUFFER_SIZES],
            variable=self._buf_str_var,
            width=320, height=30,
            font=("Segoe UI", 11),
            fg_color=SURFACE, selected_color=ACCENT, selected_hover_color="#005fa3",
            unselected_color=SURFACE, unselected_hover_color=BORDER,
            text_color=TEXT,
        ).pack(padx=20, pady=(4, 0))

        self._section_label("Input")
        self.input_var  = ctk.StringVar()
        self.input_menu = self._device_menu(self.input_var)

        self._section_label("Output")
        self.output_var  = ctk.StringVar()
        self.output_menu = self._device_menu(self.output_var)

        # Exclusive mode checkbox
        self.excl_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.excl_frame.pack(padx=20, pady=(14, 0), fill="x")
        self.exclusive_var = ctk.BooleanVar(value=cfg["exclusive"])
        self.excl_cb = ctk.CTkCheckBox(
            self.excl_frame, text="WASAPI Exclusive Mode",
            variable=self.exclusive_var,
            font=("Segoe UI", 12), text_color=TEXT,
            fg_color=ACCENT, border_color=BORDER,
            hover_color=ACCENT,
        )
        self.excl_cb.pack(side="left")

        # Apply button
        ctk.CTkButton(
            self, text="Apply", command=self._apply,
            width=320, height=36,
            font=("Segoe UI", 13, "bold"),
            fg_color=ACCENT, hover_color="#005fa3",
        ).pack(padx=20, pady=(18, 0))

        # Status line
        self.status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self.status_var,
            font=("Segoe UI", 10), text_color=SUCCESS,
        ).pack(pady=(6, 0))

        # Populate dropdowns
        self._refresh_devices(
            cfg["backend"],
            cfg.get("input_device"),
            cfg.get("output_device"),
        )
        self._sync_exclusive_state()

    def _section_label(self, text, top=10):
        ctk.CTkLabel(
            self, text=text,
            font=("Segoe UI", 10), text_color=MUTED, anchor="w",
        ).pack(anchor="w", padx=20, pady=(top, 0))

    def _device_menu(self, var):
        menu = ctk.CTkOptionMenu(
            self, values=["[ Default ]"], variable=var,
            width=320, height=32,
            fg_color=SURFACE, button_color=BORDER, button_hover_color=ACCENT,
            dropdown_fg_color=SURFACE, text_color=TEXT,
        )
        menu.pack(padx=20, pady=(4, 0))
        return menu

    # ── events ───────────────────────────────────────────────────────────────

    def _on_backend_change(self, _value):
        self._refresh_devices(self.backend_var.get())
        self._sync_exclusive_state()

    def _sync_exclusive_state(self):
        is_wasapi = self.backend_var.get() == "Windows WASAPI"
        state = "normal" if is_wasapi else "disabled"
        self.excl_cb.configure(state=state)
        if not is_wasapi:
            self.exclusive_var.set(False)

    def _refresh_devices(self, backend, restore_in=None, restore_out=None):
        inputs, outputs = get_devices(backend)
        self.input_menu.configure(values=inputs)
        self.output_menu.configure(values=outputs)

        self.input_var.set(
            restore_in if restore_in and restore_in in inputs else inputs[0]
        )
        self.output_var.set(
            restore_out if restore_out and restore_out in outputs else outputs[0]
        )

    def _apply(self):
        write_config(
            backend      = self.backend_var.get(),
            buffer_size  = int(self._buf_str_var.get()),
            input_device = self.input_var.get(),
            output_device= self.output_var.get(),
            exclusive    = self.exclusive_var.get(),
        )
        self.status_var.set("Saved — toggle audio off/on in Ableton to apply.")

if __name__ == "__main__":
    _mutex = _ensure_single_instance()
    app = FlexASIOPanel()
    app.mainloop()
