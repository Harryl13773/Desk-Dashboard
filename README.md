# Desk-Dashboard

A WiFi-connected desk display built on a Raspberry Pi Pico 2 W and a 3.5" IPS panel. A rotary encoder cycles through four screens — **Overview**, **Time**, **7-Day Forecast**, and **Agenda** — pulling live weather from [Open-Meteo](https://open-meteo.com/) and calendar events from a Google Apps Script endpoint. Powered by a single USB-C input that also drives a Qi wireless charging pad and a dual USB-A charging board.

## Features

- 🕐 **Time screen** — large segment-style clock, 12-hour format with AM/PM
- 🌤️ **7-Day Forecast** — color-coded weather conditions per day (clear, cloudy, rain, snow, storm, etc.)
- 📅 **Agenda** — upcoming calendar events grouped by day, pulled from Google Calendar
- 🖼️ **Overview** — combined at-a-glance view (time + current weather + next event), with optional custom background photo
- 🔋 **Integrated charging** — Qi wireless pad + dual USB-A ports, all from one wall cable
- 📶 **Resilient networking** — automatic WiFi reconnect and fetch retry, so the unit self-recovers from network drops
- 🎛️ **One dial, one button** — rotate to switch screens, short-press to force-refresh data, long-press to toggle the backlight

## Hardware

| Component         | Part                                      |
| ----------------- | ----------------------------------------- |
| Microcontroller   | Raspberry Pi Pico 2 W                     |
| Display           | 3.5" SPI IPS, ST7796U driver, 480×320     |
| Input             | KY-040 rotary encoder                     |
| Power negotiation | HW-398 USB-C PD trigger board (15V fixed) |
| Wireless charging | Qi transmitter, 20W max                   |
| Wired charging    | DROK dual USB-A board                     |
| Buck converter    | MP1584EN (15V → 5V for logic)             |
| USB-C input       | Treedix panel-mount breakout              |
| Enclosure         | PETG, 3D printed, two-piece (base + lid)  |

## Getting Started

### 1. Flash MicroPython

Download the **Pico 2 W**-specific UF2 from [micropython.org/download](https://micropython.org/download/) (not the plain "Pico 2" build). Hold BOOTSEL while plugging in USB, then drag the UF2 onto the `RPI-RP2` drive that appears.

### 2. Install dependencies on the Pico

In Thonny's Shell:

```python
import mip
mip.install("urequests")
```

### 3. Set up the calendar endpoint

1. Go to [script.google.com](https://script.google.com), create a new project, and paste in [`google_service.gs`](Cloud_Services/google_service.gs).
2. **Deploy → New deployment → Web app**, set "Execute as: Me" and "Who has access: Anyone".
3. Copy the deployment URL — you'll need it in the next step.

### 4. Configure and upload

Edit the top of `main.py` with your WiFi credentials, Apps Script URL, and coordinates:

```python
SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"
CALENDAR_URL = "YOUR_APPS_SCRIPT_URL"
LATITUDE = 39.7589
LONGITUDE = -84.1916
UTC_OFFSET_HOURS = -4
```

Upload `st7796.py` to `/lib/st7796.py` on the Pico, and `main.py` to the root as `main.py` (MicroPython auto-runs `main.py` on boot, so the dashboard starts without a computer attached).

## Acknowledgments

- Display driver init sequence adapted from [Bodmer/TFT_eSPI](https://github.com/Bodmer/TFT_eSPI)
- Weather data from [Open-Meteo](https://open-meteo.com/) (free, no API key required)
