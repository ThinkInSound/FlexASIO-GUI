# FlexASIO GUI

A minimal settings panel for [FlexASIO](https://github.com/dechamps/FlexASIO), the universal ASIO driver for Windows. Built with Python and CustomTkinter.

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

A prebuilt Windows binary is available in the [`dist`](dist/) folder — run `FlexASIOGUI.exe` (the `_internal` folder must stay next to the exe).

## Usage

1. **Launch the GUI once before opening your DAW** — the config file must exist before FlexASIO loads
2. Pick your backend, devices, buffer size, and exclusive mode
3. Click **Apply**
4. In your DAW, select **FlexASIO** as your ASIO driver (if audio is already running, toggle the audio device off/on to pick up changes)

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
