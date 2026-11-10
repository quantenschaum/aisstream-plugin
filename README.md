# AISStream plugin for AvNav

Use live AIS data from [aisstream.io](https://aisstream.io) in AvNav.

This plugin connects to the AISStream websocket API, filters messages around your current position, converts them to AIS NMEA (`AIVDM`) sentences, and injects them into AvNav.

## Features

- Subscribes to AISStream via websocket
- Filters traffic by a bounding box around own ship position
- Converts AISStream JSON payloads to NMEA using `pyais`
- Works as:
  - **AvNav plugin** (`Plugin` class in `plugin.py`)
  - **Standalone AIS-to-NMEA server** (CLI mode)

## Requirements

- Python **3.11+**
- AISStream API key
- AvNav with valid own-ship position (`gps.lat`, `gps.lon`) for plugin mode

Dependencies are defined in `pyproject.toml`.

## AvNav plugin installation

1. Copy this directory to your AvNav plugins folder:

   ```text
   avnav/plugins/aisstream
   ```

2. Restart AvNav.
3. Open plugin settings and configure

### Plugin configuration parameters

| Parameter  | Type   | Description                                       |
| ---------- | ------ | ------------------------------------------------- |
| `apiws`    | STRING | AISStream websocket endpoint                      |
| `apikey`   | STRING | Your AISStream API key                            |
| `distance` | FLOAT  | Poll radius around own position in nautical miles |

## Standalone usage (CLI)

`plugin.py` can also run outside AvNav and expose AIS NMEA over TCP or UDP.

You can use it to feed AIS data into [OsmAnd](https://osmand.net/docs/user/plugins/ais-tracker/).

### Install locally with uv

```sh
uv venv --python 3.11
source .venv/bin/activate
uv sync
```

### Run

```sh
python plugin.py <lat> <lon> <radius_nm> --apikey <YOUR_API_KEY>
```

Example:

```sh
python plugin.py 53.5 9.9 20 --apikey your_key_here
```

By default this starts a **TCP server** on `0.0.0.0:10110`.

For options call with `-h`.

## How message filtering works

The plugin creates a bounding box centered at your current position and sized from `distance` (nautical miles). It refreshes the subscription periodically.
