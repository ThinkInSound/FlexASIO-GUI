#!/usr/bin/env python3
"""FlexASIO Settings — simple driver configuration panel."""

import ctypes
import re
import subprocess
import sys
import threading
import time
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

CONFIG_PATH       = Path.home() / "FlexASIO.toml"
LOG_PATH          = Path.home() / "FlexASIO.log"
PORT_AUDIO_EXE    = Path(r"C:\Program Files\FlexASIO\x64\PortAudioDevices.exe")
FLEXASIO_TEST_EXE = Path(r"C:\Program Files\FlexASIO\x64\FlexASIOTest.exe")

# FlexASIO logs whenever ~/FlexASIO.log exists and never rotates it; a debug
# log someone forgot to turn off grows until the driver's 1 GiB hard cap.
MAX_LOG_BYTES = 16 * 1024 * 1024

# DirectSound and WDM-KS are deliberately absent: on this machine both hang
# or crash the driver at stream start (flakily — an apply-time test pass
# doesn't make them safe in the DAW), verified 2026-07-14.
BACKENDS     = ["Windows WASAPI", "MME"]
BUFFER_SIZES = [128, 256, 512, 1024, 2048]

# ── device enumeration via PortAudioDevices.exe ───────────────────────────────

def _parse_port_audio_devices():
    """Run PortAudioDevices.exe and return list of device dicts."""
    result = subprocess.run(
        [str(PORT_AUDIO_EXE)],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
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

def read_config(text=None):
    """Parse config settings. Reads CONFIG_PATH when ``text`` is None
    (returning defaults if the file is missing); pass ``text`` to parse a
    snapshot instead."""
    defaults = {
        "backend":           "Windows WASAPI",
        "bufferSizeSamples": 256,
        # Input defaults to disabled: opening the default capture device
        # drags virtual mics (DroidCam/NDI/Steam) into the driver, and
        # their stream teardown can hang the DAW.
        "input_device":      "[ Disabled ]",
        "output_device":     "[ Default output ]",
        "exclusive":         False,
    }
    if text is None:
        if not CONFIG_PATH.exists():
            return defaults
        text = CONFIG_PATH.read_text(encoding="utf-8")

    def g(pattern, text, cast=str, default=None):
        m = re.search(pattern, text, re.MULTILINE)
        return cast(m.group(1)) if m else default

    cfg = dict(defaults)
    cfg["backend"]           = g(r'^backend\s*=\s*"([^"]*)"', text) or defaults["backend"]
    if cfg["backend"] not in BACKENDS:  # e.g. config written before a backend was dropped
        cfg["backend"] = defaults["backend"]
    cfg["bufferSizeSamples"] = g(r'^bufferSizeSamples\s*=\s*(\d+)', text, int) or defaults["bufferSizeSamples"]

    # In an existing file, no device line means FlexASIO uses the default
    # device — the disabled-input default above only applies to missing files.
    cfg["input_device"] = "[ Default input ]"

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
            # No suggestedLatencySeconds here: 0.0 pins PortAudio to its
            # minimum buffering regardless of bufferSizeSamples, which
            # glitches in full duplex. The default (3x the ASIO buffer) is
            # reliable and leaves the buffer setting in control of latency.
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


def test_driver():
    """Test whether FlexASIO works with the current config file.

    Returns "ok", "fail" (driver can't initialize), or "hang" (driver
    initializes but never returns from stream start — a DAW loading this
    config would lock up the same way; DirectSound does this on some
    setups). When the check itself can't run, returns "ok" rather than
    lock the user out.
    """
    if not FLEXASIO_TEST_EXE.exists():
        return "ok"
    try:
        result = subprocess.run(
            [str(FLEXASIO_TEST_EXE)],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "ok" if result.returncode == 0 else "fail"
    except subprocess.TimeoutExpired:
        return "hang"
    except Exception:
        return "ok"


# The driver watches FlexASIO.toml: a DAW that is currently streaming picks up
# a config change within about a second by restarting its audio engine
# (kAsioResetRequest). Racing FlexASIOTest against that always loses — the DAW
# grabs the device first — so when a live pickup is detected, the verdict comes
# from the driver log instead of FlexASIOTest.
_RESET_MARKER      = "Issuing reset request due to config change"
_CREATEBUFFERS_RE  = re.compile(r'EXITING CONTEXT: createBuffers\(\) (.*)')

def _read_log_from(offset):
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            return f.read()
    except OSError:
        return ""


def _apply_and_verify(cfg_args, progress):
    """Write the config, then verify the driver accepts it.

    Returns "ok"/"fail"/"hang" when verified via FlexASIOTest, or
    "daw-ok"/"daw-fail" when a DAW was streaming and verified it live.
    ``progress(msg)`` reports status text along the way (called off the Tk
    thread; the caller polls).
    """
    created_log = not LOG_PATH.exists()
    if created_log:
        try:
            LOG_PATH.touch()  # existence of the file enables driver logging
        except OSError:
            created_log = False
    try:
        offset = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0
    except OSError:
        offset = 0

    try:
        write_config(**cfg_args)

        deadline = time.monotonic() + 2.0
        reset_seen = False
        while time.monotonic() < deadline:
            if _RESET_MARKER in _read_log_from(offset):
                reset_seen = True
                break
            time.sleep(0.2)

        if not reset_seen:
            return test_driver()  # no live driver instance; safe to self-test

        progress("Ableton picked up the change — restarting its audio…")
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            statuses = _CREATEBUFFERS_RE.findall(_read_log_from(offset))
            if statuses:
                return "daw-ok" if statuses[-1].startswith("[OK]") else "daw-fail"
            time.sleep(0.3)
        return "daw-fail"  # DAW never came back up with these settings
    finally:
        if created_log:
            try:
                LOG_PATH.unlink()  # stop driver logging again
            except OSError:
                pass  # driver may still hold it; size cap cleanup handles it

# ── UI ────────────────────────────────────────────────────────────────────────

BG        = "#1e1e1e"
SURFACE   = "#2a2a2a"
BORDER    = "#3a3a3a"
ACCENT    = "#0078d4"
TEXT      = "#e8e8e8"
MUTED     = "#888888"
SUCCESS   = "#4ec94e"
ERROR     = "#e05d5d"

class _ToolTip:
    """Hover tooltip for a widget (customtkinter has no built-in one)."""

    def __init__(self, widget, text, delay_ms=400):
        self.widget, self.text, self.delay_ms = widget, text, delay_ms
        self._after_id, self._tip = None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip is not None:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = ctk.CTkToplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.attributes("-topmost", True)
        ctk.CTkLabel(
            self._tip, text=self.text,
            font=("Segoe UI", 10), text_color=TEXT,
            fg_color=SURFACE, corner_radius=6,
            wraplength=280, justify="left",
            padx=10, pady=6,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _cancel(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None


class FlexASIOPanel(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title("FlexASIO")
        self.geometry("360x472")
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
        self._pre_exclusive_input = None
        self.excl_cb = ctk.CTkCheckBox(
            self.excl_frame, text="WASAPI Exclusive Mode",
            variable=self.exclusive_var,
            command=self._on_exclusive_toggle,
            font=("Segoe UI", 12), text_color=TEXT,
            fg_color=ACCENT, border_color=BORDER,
            hover_color=ACCENT,
        )
        self.excl_cb.pack(side="left")
        _ToolTip(
            self.excl_cb,
            'Requires "Allow applications to take exclusive control of this '
            'device" to be enabled in Windows sound device properties '
            "(mmsys.cpl → device → Properties → Advanced). "
            "Without it the driver cannot start and these settings will be "
            "rejected.",
        )

        # Apply button
        self.apply_btn = ctk.CTkButton(
            self, text="Apply", command=self._apply,
            width=320, height=36,
            font=("Segoe UI", 13, "bold"),
            fg_color=ACCENT, hover_color="#005fa3",
        )
        self.apply_btn.pack(padx=20, pady=(18, 0))

        # Status line
        self.status_var = ctk.StringVar(value="")
        self.status_label = ctk.CTkLabel(
            self, textvariable=self.status_var,
            font=("Segoe UI", 10), text_color=SUCCESS,
            wraplength=320,
        )
        self.status_label.pack(pady=(6, 0))

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

    def _on_exclusive_toggle(self):
        """Suggest half duplex when exclusive is switched on.

        Exclusive full duplex glitches when the input and output devices
        run on different clocks (44.1 kHz mic vs 48 kHz output here), so
        checking the box parks the input on [ Disabled ]. It is only a
        suggestion — the input menu stays enabled and any device can be
        re-selected before applying.
        """
        if self.exclusive_var.get():
            if self.input_var.get() != "[ Disabled ]":
                self._pre_exclusive_input = self.input_var.get()
                self.input_var.set("[ Disabled ]")
                self.status_label.configure(text_color=MUTED)
                self.status_var.set(
                    "Input set to [ Disabled ]: exclusive mode glitches "
                    "when mic and output clocks differ. Re-select an input "
                    "above if you need one."
                )
        else:
            if self._pre_exclusive_input and self.input_var.get() == "[ Disabled ]":
                self.input_var.set(self._pre_exclusive_input)
                self.status_label.configure(text_color=MUTED)
                self.status_var.set("Input selection restored.")
            self._pre_exclusive_input = None

    def _sync_exclusive_state(self):
        is_wasapi = self.backend_var.get() == "Windows WASAPI"
        state = "normal" if is_wasapi else "disabled"
        self.excl_cb.configure(state=state)
        if not is_wasapi:
            self.exclusive_var.set(False)

    def _sync_ui_to_config(self, cfg):
        """Point every control back at what the config file actually says."""
        self.backend_var.set(cfg["backend"])
        self._buf_str_var.set(str(cfg["bufferSizeSamples"]))
        self._refresh_devices(
            cfg["backend"], cfg.get("input_device"), cfg.get("output_device")
        )
        self.exclusive_var.set(cfg["exclusive"])
        self._sync_exclusive_state()

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
        previous = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None

        self.apply_btn.configure(state="disabled")
        self.status_label.configure(text_color=MUTED)
        self.status_var.set("Applying settings…")

        cfg_args = dict(
            backend      = self.backend_var.get(),
            buffer_size  = int(self._buf_str_var.get()),
            input_device = self.input_var.get(),
            output_device= self.output_var.get(),
            exclusive    = self.exclusive_var.get(),
        )

        # _apply_and_verify blocks (FlexASIOTest timeout / DAW reload watch),
        # so run it off the Tk thread. Tkinter calls are not thread-safe, so
        # the worker only stores results; the Tk thread polls for them.
        result = {}

        def worker():
            result["verdict"] = _apply_and_verify(
                cfg_args, progress=lambda msg: result.__setitem__("status", msg)
            )

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if "verdict" in result:
                self._finish_apply(result["verdict"], previous)
                return
            if "status" in result:
                self.status_var.set(result.pop("status"))
            self.after(100, poll)

        self.after(100, poll)

    def _finish_apply(self, verdict, previous):
        self.apply_btn.configure(state="normal")

        if verdict in ("ok", "daw-ok"):
            self.status_label.configure(text_color=SUCCESS)
            self.status_var.set(
                "Saved — Ableton restarted its audio with the new settings."
                if verdict == "daw-ok"
                else "Saved — toggle audio off/on in Ableton to apply."
            )
            return

        # The driver can't work with these settings; roll back so the DAW
        # never sees a known-broken config. Re-write the previous settings
        # through write_config instead of restoring the raw bytes: an old
        # file can carry options this GUI no longer writes (e.g. the
        # glitch-prone suggestedLatencySeconds = 0.0), and a byte-exact
        # restore would resurrect them.
        if previous is None:
            CONFIG_PATH.unlink(missing_ok=True)
        else:
            prev = read_config(previous)
            write_config(
                backend       = prev["backend"],
                buffer_size   = prev["bufferSizeSamples"],
                input_device  = prev["input_device"],
                output_device = prev["output_device"],
                exclusive     = prev["exclusive"],
            )

        # Snap every control back to the rolled-back config so the UI
        # never advertises a state the driver just refused (an exclusive
        # failure can surface as "hang", not just "fail", so this must
        # not depend on the verdict).
        tried_exclusive = self.exclusive_var.get()
        self._sync_ui_to_config(read_config())

        if tried_exclusive and not self.exclusive_var.get():
            msg = (
                "Rejected: driver can't start in exclusive mode — another "
                "app may be holding the device, or exclusive access is off "
                "in Windows sound device properties (mmsys.cpl). "
                "Exclusive mode has been switched back off."
            )
        elif verdict == "hang":
            msg = (
                "Rejected: driver locks up when audio starts with these "
                "settings — a DAW using them would freeze. This backend "
                "may not work on this system. Previous settings kept."
            )
        elif self.exclusive_var.get():
            # Exclusive was already on and stays on — the rejected change
            # was something else, most likely the buffer size, which the
            # hardware constrains tightly in exclusive mode.
            msg = (
                "Rejected: driver can't start with these settings. In "
                "exclusive mode the hardware only accepts certain buffer "
                "sizes — try a different size. Previous settings kept."
            )
        else:
            msg = (
                "Rejected: driver can't start with these settings. "
                "Previous settings kept."
            )
        if verdict == "daw-fail":
            # The failed instance is gone, so the restored config won't be
            # picked up automatically — the DAW needs an audio restart.
            msg += (
                " If Ableton shows a driver error, toggle audio off/on in "
                "its preferences to recover."
            )
        self.status_var.set(msg)
        self.status_label.configure(text_color=ERROR)

def _init_config():
    """Write a default FlexASIO.toml if none exists, then exit.

    Meant to be run headless (``FlexASIOGUI.exe --init``) by an installer
    or a RunOnce registry entry, so FlexASIO has a config file before the
    DAW first loads the driver.
    """
    if not CONFIG_PATH.exists():
        cfg = read_config()  # returns defaults when the file is missing
        write_config(
            backend       = cfg["backend"],
            buffer_size   = cfg["bufferSizeSamples"],
            input_device  = cfg["input_device"],
            output_device = cfg["output_device"],
            exclusive     = cfg["exclusive"],
        )


def _scrub_stale_pins():
    """Drop pinned devices that are no longer present.

    FlexASIO refuses to initialize at all when a pinned device is missing,
    so fall back to the system default rather than leave a dead pin.
    """
    if not CONFIG_PATH.exists():
        return
    cfg = read_config()
    inputs, outputs = get_devices(cfg["backend"])
    if _device_cache is None:
        return  # enumeration failed; can't tell what's stale
    scrubbed = dict(cfg)
    if cfg["input_device"] not in inputs:
        scrubbed["input_device"] = "[ Disabled ]"
    if cfg["output_device"] not in outputs:
        scrubbed["output_device"] = "[ Default output ]"
    if scrubbed != cfg:
        write_config(
            backend       = scrubbed["backend"],
            buffer_size   = scrubbed["bufferSizeSamples"],
            input_device  = scrubbed["input_device"],
            output_device = scrubbed["output_device"],
            exclusive     = scrubbed["exclusive"],
        )


def _reap_oversized_log():
    """Delete a forgotten debug log before it grows unbounded.

    FlexASIO logs whenever LOG_PATH exists; anyone who enabled logging for a
    support session and forgot about it otherwise pays the overhead forever
    and ends up with a gigabyte-scale file.
    """
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
            LOG_PATH.unlink()
    except OSError:
        pass  # in use or access denied; try again next launch


if __name__ == "__main__":
    if "--init" in sys.argv:
        _init_config()
        _scrub_stale_pins()
        _reap_oversized_log()
        sys.exit(0)
    _mutex = _ensure_single_instance()
    _scrub_stale_pins()
    _reap_oversized_log()
    app = FlexASIOPanel()
    app.mainloop()
