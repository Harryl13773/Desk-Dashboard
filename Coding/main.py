import network
import time
import ntptime
import urequests
import framebuf
from machine import Pin, SPI, PWM
from Coding.lib.st7796 import ST7796

# Config 
SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"
CALENDAR_URL = "YOUR_APPS_SCRIPT_URL"
LATITUDE = 39.7589
LONGITUDE = -84.1916
UTC_OFFSET_HOURS = -4  # EDT; -5 for EST

WEATHER_REFRESH_MS = 900_000
CALENDAR_REFRESH_MS = 300_000
FETCH_RETRY_MS = 30_000
WIFI_CHECK_INTERVAL_MS = 10_000
WIFI_RECONNECT_TIMEOUT_S = 10
LONG_PRESS_MS = 600

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
WEEKDAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
SCREEN_NAMES = ["OVERVIEW", "TIME", "FORECAST", "AGENDA"]
screen_index = 0

# WiFi 
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)
print("Connecting", end="")
start = time.time()
while not wlan.isconnected():
    if time.time() - start > 15:
        print("\nFailed to connect.")
        raise SystemExit
    print(".", end="")
    time.sleep(0.5)
print("\nConnected!")

print("Syncing time...")
ntptime.settime()
print("Time synced.")

def get_local_time():
    return time.localtime(time.time() + UTC_OFFSET_HOURS * 3600)

# Display
Pin(21, Pin.OUT).value(0)
time.sleep(0.1)
spi = SPI(0, baudrate=10_000_000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
cs, dc, rst = Pin(17), Pin(16), Pin(20)
backlight = PWM(Pin(21))
backlight.freq(1000)
backlight.duty_u16(65535)
display = ST7796(spi, cs, dc, rst)
screen_on = True

# Background image (streamed directly into display.buffer)
def draw_background():
    try:
        with open("background.bin", "rb") as f:
            f.readinto(display.buffer)
    except Exception:
        display.fill(0x0000)

# Encoder: interrupt-driven, full-cycle validated (bounce-proof)
clk = Pin(2, Pin.IN, Pin.PULL_UP)
dt = Pin(3, Pin.IN, Pin.PULL_UP)
sw = Pin(4, Pin.IN, Pin.PULL_UP)

_enc_last_state = (clk.value() << 1) | dt.value()
_enc_raw_delta = 0
encoder_delta = 0

_ENC_TRANSITIONS = {
    (0b00, 0b01): 1, (0b01, 0b11): 1, (0b11, 0b10): 1, (0b10, 0b00): 1,
    (0b00, 0b10): -1, (0b10, 0b11): -1, (0b11, 0b01): -1, (0b01, 0b00): -1,
}

def encoder_isr(pin):
    global _enc_last_state, _enc_raw_delta, encoder_delta
    state = (clk.value() << 1) | dt.value()
    if state != _enc_last_state:
        _enc_raw_delta += _ENC_TRANSITIONS.get((_enc_last_state, state), 0)
        _enc_last_state = state
        if state == 0b00:
            if _enc_raw_delta > 0:
                encoder_delta += 1
            elif _enc_raw_delta < 0:
                encoder_delta -= 1
            _enc_raw_delta = 0

clk.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=encoder_isr)
dt.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=encoder_isr)
press_start = None

# WiFi health check / auto-reconnect
def ensure_wifi():
    global next_weather_attempt, next_calendar_attempt
    if wlan.isconnected():
        return
    print("WiFi dropped, reconnecting...")
    try:
        wlan.disconnect()
    except Exception:
        pass
    wlan.connect(SSID, PASSWORD)
    retry_start = time.time()
    while not wlan.isconnected() and time.time() - retry_start < WIFI_RECONNECT_TIMEOUT_S:
        time.sleep(0.5)
    if wlan.isconnected():
        print("WiFi reconnected!")
        next_weather_attempt = 0
        next_calendar_attempt = 0
    else:
        print("Reconnect attempt failed, will retry.")

# Drawing helpers
DIGIT_SEGMENTS = {
    '0': [1,1,1,1,1,1,0], '1': [0,1,1,0,0,0,0], '2': [1,1,0,1,1,0,1],
    '3': [1,1,1,1,0,0,1], '4': [0,1,1,0,0,1,1], '5': [1,0,1,1,0,1,1],
    '6': [1,0,1,1,1,1,1], '7': [1,1,1,0,0,0,0], '8': [1,1,1,1,1,1,1],
    '9': [1,1,1,1,0,1,1],
}

def draw_digit(x, y, d, w, h, t, color):
    if d is None:
        return
    gap = max(2, t // 3)
    half = h // 2
    s = DIGIT_SEGMENTS[d]
    if s[0]: display.fill_rect(x+t, y, w-2*t, t, color)
    if s[1]: display.fill_rect(x+w-t, y+t+gap, t, half-t-gap*2, color)
    if s[2]: display.fill_rect(x+w-t, y+half+gap, t, half-t-gap*2, color)
    if s[3]: display.fill_rect(x+t, y+h-t, w-2*t, t, color)
    if s[4]: display.fill_rect(x, y+half+gap, t, half-t-gap*2, color)
    if s[5]: display.fill_rect(x, y+t+gap, t, half-t-gap*2, color)
    if s[6]: display.fill_rect(x+t, y+half-t//2, w-2*t, t, color)

def draw_colon(x, y, h, size, color):
    display.fill_rect(x, y+h//3, size, size, color)
    display.fill_rect(x, y+2*h//3, size, size, color)

def draw_text_scaled(text, x, y, color, scale):
    tmp_w = len(text) * 8
    tmp_h = 8
    tmp_buf = bytearray(tmp_w * tmp_h * 2)
    tmp = framebuf.FrameBuffer(tmp_buf, tmp_w, tmp_h, framebuf.RGB565)
    tmp.fill(0)
    tmp.text(text, 0, 0, color)
    for ty in range(tmp_h):
        for tx in range(tmp_w):
            idx = (ty * tmp_w + tx) * 2
            if tmp_buf[idx] != 0 or tmp_buf[idx+1] != 0:
                display.fill_rect(x + tx*scale, y + ty*scale, scale, scale, color)

def draw_centered(text, y, color, scale, screen_w=480):
    x = (screen_w - len(text) * 8 * scale) // 2
    draw_text_scaled(text, x, y, color, scale)

def draw_col_centered(text, col_x, col_w, y, color, scale):
    tw = len(text) * 8 * scale
    x = col_x + (col_w - tw) // 2
    draw_text_scaled(text, x, y, color, scale)

def draw_circle(cx, cy, r, color):
    for dy in range(-r, r + 1):
        span = int((r * r - dy * dy) ** 0.5)
        display.hline(cx - span, cy + dy, span * 2, color)

def truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."

def format_hm(hour24, minute):
    period = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return hour12, minute, period

def parse_iso(dt_str):
    return (int(dt_str[0:4]), int(dt_str[5:7]), int(dt_str[8:10]),
             int(dt_str[11:13]), int(dt_str[14:16]), int(dt_str[17:19]), 0, 0)

def to_local_time(dt_str):
    utc_epoch = time.mktime(parse_iso(dt_str))
    return time.localtime(utc_epoch + UTC_OFFSET_HOURS * 3600)

def format_date(lt):
    return "{}, {} {}".format(WEEKDAYS[lt[6]], MONTHS[lt[1]-1], lt[2])

def format_time_str(lt):
    h, m, p = format_hm(lt[3], lt[4])
    return "{}:{:02d} {}".format(h, m, p)

WEATHER_CODE_INFO = {
    0: ("CLR", 0xFFE0), 1: ("CLR", 0xFFE0), 2: ("CLD", 0xC618), 3: ("OVC", 0x8410),
    45: ("FOG", 0x8410), 48: ("FOG", 0x8410),
    51: ("DRZ", 0x5D9C), 53: ("DRZ", 0x5D9C), 55: ("DRZ", 0x5D9C),
    56: ("DRZ", 0x5D9C), 57: ("DRZ", 0x5D9C),
    61: ("RAIN", 0x001F), 63: ("RAIN", 0x001F), 65: ("RAIN", 0x001F),
    66: ("RAIN", 0x001F), 67: ("RAIN", 0x001F),
    71: ("SNW", 0xFFFF), 73: ("SNW", 0xFFFF), 75: ("SNW", 0xFFFF), 77: ("SNW", 0xFFFF),
    80: ("SHWR", 0x001F), 81: ("SHWR", 0x001F), 82: ("SHWR", 0x001F),
    95: ("STRM", 0xF800), 96: ("STRM", 0xF800), 99: ("STRM", 0xF800),
}

def get_weather_info(code):
    return WEATHER_CODE_INFO.get(code, ("N/A", 0x8410))

# Data fetching
cached_current_temp = None
cached_current_code = None
cached_highs = None
cached_lows = None
cached_codes = None
cached_events = []
weather_loaded = False
calendar_loaded = False
next_weather_attempt = 0
next_calendar_attempt = 0

def fetch_weather():
    global cached_current_temp, cached_current_code, cached_highs, cached_lows, cached_codes
    url = ("https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}"
           "&current_weather=true&daily=temperature_2m_max,temperature_2m_min,weathercode"
           "&temperature_unit=fahrenheit&timezone=auto&forecast_days=7").format(LATITUDE, LONGITUDE)
    response = urequests.get(url)
    data = response.json()
    response.close()
    cached_current_temp = round(data["current_weather"]["temperature"])
    cached_current_code = data["current_weather"]["weathercode"]
    cached_highs = data["daily"]["temperature_2m_max"]
    cached_lows = data["daily"]["temperature_2m_min"]
    cached_codes = data["daily"]["weathercode"]

def fetch_calendar():
    global cached_events
    response = urequests.get(CALENDAR_URL)
    cached_events = response.json()
    response.close()

# Screen: Overview
def draw_overview():
    draw_background()
    lt = get_local_time()

    draw_text_scaled(format_date(lt), 10, 8, 0x07FF, 2)

    h, m, p = format_hm(lt[3], lt[4])
    hstr = str(h)
    h_tens = hstr[0] if len(hstr) == 2 else None
    h_ones = hstr[-1]
    mstr = "{:02d}".format(m)
    w, dh, t = 38, 76, 8
    y = 45
    x = 10
    draw_digit(x, y, h_tens, w, dh, t, 0xFFFF); x += w + 6
    draw_digit(x, y, h_ones, w, dh, t, 0xFFFF); x += w + 10
    draw_colon(x, y, dh, 8, 0xFFFF); x += 8 + 10
    draw_digit(x, y, mstr[0], w, dh, t, 0xFFFF); x += w + 6
    draw_digit(x, y, mstr[1], w, dh, t, 0xFFFF); x += w + 10
    draw_text_scaled(p, x, y + dh - 24, 0xFFFF, 3)

    col_x, col_w = 330, 140
    if weather_loaded:
        label, color = get_weather_info(cached_current_code)
        draw_circle(col_x + col_w // 2, 55, 22, color)
        draw_col_centered("{}F".format(cached_current_temp), col_x, col_w, 90, 0xFC00, 3)
        draw_col_centered(label, col_x, col_w, 135, color, 2)
    else:
        draw_col_centered("Loading...", col_x, col_w, 80, 0x8410, 1)

    display.hline(10, 210, 460, 0x39C7)

    draw_text_scaled("NEXT EVENT", 10, 225, 0x07FF, 1)
    if calendar_loaded and len(cached_events) > 0:
        ev = cached_events[0]
        elt = to_local_time(ev["start"])
        line = "{}  {}".format(format_date(elt), format_time_str(elt))
        draw_text_scaled(line, 10, 245, 0xFFE0, 2)
        draw_text_scaled(truncate(ev["title"], 34), 10, 275, 0xFFFF, 2)
    elif calendar_loaded:
        draw_text_scaled("No upcoming events", 10, 255, 0x8410, 2)
    else:
        draw_text_scaled("Loading calendar...", 10, 255, 0x8410, 1)

    display.show()

# Screen: Time
def draw_time_screen():
    display.fill(0x0000)
    lt = get_local_time()
    h, m, p = format_hm(lt[3], lt[4])
    hstr = str(h)
    h_tens = hstr[0] if len(hstr) == 2 else None
    h_ones = hstr[-1]
    mstr = "{:02d}".format(m)

    w, dh, t = 70, 140, 12
    y = 90
    color = 0xFFFF
    x = 20
    draw_digit(x, y, h_tens, w, dh, t, color); x += w + 10
    draw_digit(x, y, h_ones, w, dh, t, color); x += w + 15
    draw_colon(x, y, dh, 14, color); x += 14 + 15
    draw_digit(x, y, mstr[0], w, dh, t, color); x += w + 10
    draw_digit(x, y, mstr[1], w, dh, t, color); x += w + 12
    draw_text_scaled(p, x, y + (dh - 32)//2, color, 4)

    display.show()

# Screen: Forecast
def draw_forecast_screen():
    display.fill(0x0000)
    if not weather_loaded:
        draw_centered("Loading forecast...", 140, 0x8410, 2)
        display.show()
        return

    lt = get_local_time()
    today_wd = lt[6]
    draw_text_scaled("7-DAY FORECAST", 8, 6, 0xFFFF, 2)

    col_w = 68
    for i in range(7):
        x = 6 + i * col_w
        wd_name = WEEKDAYS[(today_wd + i) % 7]
        label, color = get_weather_info(cached_codes[i])
        draw_col_centered(wd_name, x, col_w, 40, 0xFFFF, 2)
        draw_circle(x + col_w // 2, 84, 14, color)
        draw_col_centered(label, x, col_w, 106, color, 1)
        hi = str(round(cached_highs[i]))
        lo = str(round(cached_lows[i]))
        draw_col_centered(hi, x, col_w, 130, 0xFC00, 3)
        draw_col_centered(lo, x, col_w, 170, 0x5D9C, 2)

    display.show()

# Screen: Agenda
def draw_agenda_screen():
    display.fill(0x0000)
    draw_centered("UPCOMING EVENTS", 8, 0x07FF, 2)

    if not calendar_loaded:
        draw_centered("Loading...", 140, 0x8410, 2)
        display.show()
        return
    if len(cached_events) == 0:
        draw_centered("No upcoming events", 140, 0x8410, 2)
        display.show()
        return

    y = 42
    last_date_key = None
    max_y = 300
    for event in cached_events:
        lt = to_local_time(event["start"])
        date_key = (lt[0], lt[1], lt[2])
        if date_key != last_date_key:
            if y + 20 > max_y:
                break
            draw_text_scaled(format_date(lt), 10, y, 0xFFE0, 2)
            y += 26
            last_date_key = date_key
        if y + 16 > max_y:
            break
        draw_text_scaled(format_time_str(lt), 30, y, 0x07E0, 1)
        title_x = 30 + 72
        max_chars = (480 - title_x - 10) // 8
        draw_text_scaled(truncate(event["title"], max_chars), title_x, y, 0xFFFF, 1)
        y += 18

    display.show()

def draw_current_screen():
    if screen_index == 0:
        draw_overview()
    elif screen_index == 1:
        draw_time_screen()
    elif screen_index == 2:
        draw_forecast_screen()
    elif screen_index == 3:
        draw_agenda_screen()

# Main loop
last_minute = -1
needs_redraw = True
next_wifi_check = 0
print("Dashboard running. Turn to switch screens, long-press to toggle backlight.")

while True:
    now_ms = time.ticks_ms()

    if time.ticks_diff(now_ms, next_wifi_check) >= 0:
        ensure_wifi()
        next_wifi_check = time.ticks_add(now_ms, WIFI_CHECK_INTERVAL_MS)

    if wlan.isconnected():
        if time.ticks_diff(now_ms, next_weather_attempt) >= 0:
            try:
                fetch_weather()
                weather_loaded = True
                needs_redraw = True
                next_weather_attempt = time.ticks_add(now_ms, WEATHER_REFRESH_MS)
            except Exception as e:
                print("Weather fetch failed:", e)
                next_weather_attempt = time.ticks_add(now_ms, FETCH_RETRY_MS)

        if time.ticks_diff(now_ms, next_calendar_attempt) >= 0:
            try:
                fetch_calendar()
                calendar_loaded = True
                needs_redraw = True
                next_calendar_attempt = time.ticks_add(now_ms, CALENDAR_REFRESH_MS)
            except Exception as e:
                print("Calendar fetch failed:", e)
                next_calendar_attempt = time.ticks_add(now_ms, FETCH_RETRY_MS)

    lt = get_local_time()
    if lt[4] != last_minute:
        last_minute = lt[4]
        if screen_index in (0, 1):
            needs_redraw = True

    if encoder_delta != 0:
        if encoder_delta > 0:
            screen_index = (screen_index + 1) % 4
        else:
            screen_index = (screen_index - 1) % 4
        encoder_delta = 0
        needs_redraw = True
        print("Screen:", SCREEN_NAMES[screen_index])

    if sw.value() == 0 and press_start is None:
        press_start = time.ticks_ms()
    elif sw.value() == 1 and press_start is not None:
        held_for = time.ticks_diff(time.ticks_ms(), press_start)
        if held_for >= LONG_PRESS_MS:
            screen_on = not screen_on
            backlight.duty_u16(65535 if screen_on else 0)
            print("Screen ON" if screen_on else "Screen OFF")
        else:
            print("Manual refresh triggered")
            next_weather_attempt = 0
            next_calendar_attempt = 0
        press_start = None
        time.sleep(0.05)

    if needs_redraw and screen_on:
        draw_current_screen()
        needs_redraw = False

    time.sleep(0.02)