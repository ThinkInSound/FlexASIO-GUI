# FlexASIO GUI

A minimal settings panel for [FlexASIO](https://github.com/dechamps/FlexASIO), the universal ASIO driver for Windows. Built with Python and CustomTkinter.

<img width="462" height="552" alt="flexasiogui" src="https://github.com/user-attachments/assets/8e40d746-b80f-4889-bc72-277e735ec7cc" />

## Features

- **Independent input/output device selection** — route input and output to different hardware devices, or disable either side entirely
- **Backend selection** — choose between Windows WASAPI, DirectSound, WDM-KS, and MME host APIs
- **WASAPI Exclusive Mode toggle** — enable low-latency exclusive access (automatically sets `suggestedLatencySeconds = 0.0`)
- **Buffer size selection** — 128 / 256 / 512 / 1024 / 2048 samples
- Single-instance app: launching it again focuses the existing window

Settings are written to `FlexASIO.toml` in your user profile folder, which FlexASIO reads on startup.

## Requirements

- Windows 10/11
- [FlexASIO](https://github.com/dechamps/FlexASIO/releases) installed to the default location (`C:\Program Files\FlexASIO`) — the GUI uses its bundled `PortAudioDevices.exe` for device enumeration

## Download

From the [Releases page](https://github.com/ThinkInSound/FlexASIO-GUI/releases):

- **`FlexASIOGUI-Setup.exe`** (recommended) — installs per-user (no admin prompt), adds a Start Menu shortcut, and creates a default config automatically, so no first-launch step is needed before your DAW
- **`FlexASIOGUI-portable.zip`** — unzip anywhere and run `FlexASIOGUI.exe` (keep the `_internal` folder next to the exe). For portable use, run `FlexASIOGUI.exe --init` once, or launch the GUI and click Apply, before first using FlexASIO in a DAW

## Usage

1. Pick your backend, devices, buffer size, and exclusive mode
2. Click **Apply**
3. In your DAW, select **FlexASIO** as your ASIO driver (if audio is already running, toggle the audio device off/on to pick up changes)

The FlexASIO driver itself is loaded directly by the DAW — this GUI only edits the config file and does not need to be running while you play.

### First-run setup (no GUI required)

FlexASIO reads `%USERPROFILE%\FlexASIO.toml` when the DAW loads the driver. To make sure that file exists before the first DAW session, run once:

```
FlexASIOGUI.exe --init
```

This silently writes a default config (WASAPI, shared mode, 256-sample buffer, default devices) and exits — it never touches an existing config. To automate it, add a RunOnce registry entry after installing (fires at next login, then removes itself):

```
reg add HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce /v FlexASIOInit /t REG_SZ /d "\"C:\path\to\dist\FlexASIOGUI.exe\" --init"
```

Or call it from an installer's post-install step.

## Running from source

```
pip install customtkinter
python flexasio_settings.py
```

## Building the binary

```
pip install pyinstaller
pyinstaller --noconsole --name FlexASIOGUI flexasio_settings.py
```

## Files

- `flexasio_settings.py` — the application
- `register_flexasio.bat` — re-registers the FlexASIO COM server (run as admin) if the driver stops appearing in your DAW
- `dist/` — prebuilt Windows binary

## License

MIT
