## Arduino UNO Q — App Lab

> **Version stamp (fill in / update when re-verified):**
> App Lab version: `____` · Board image / firmware: `____` · `arduino:zephyr` platform: `____` · Last verified: `____`
>
> **Confidence markers used below:**
> - *(documented)* = confirmed in Arduino docs or official example repos.
> - *(observed)* = found by testing; not confirmed in public docs. Re-verify if behavior changes.
> - Unmarked statements are believed correct but should be treated as version-dependent.

### Hardware
- **MCU**: STM32U585, runs Zephyr OS, executes Arduino sketch (C++). Owns GPIO, PWM, sensors, real-time control.
- **MPU**: Qualcomm QRB2210, runs Debian Linux, executes Python script. Owns networking, AI, heavy compute.
- Communication: RPC via `Arduino_RouterBridge` over an internal serial link (never open `/dev/ttyHS1` or `Serial1` directly).
- Onboard: 8×13 LED matrix, 4 RGB LEDs, Qwiic connector (works with Modulino sensors). Wi-Fi 5, Bluetooth 5.1.
- Interfaces: I2C/I3C, SPI, UART, CAN, PWM, ADC.

### App File Structure
```
my_app/
├── app.yaml              # Linux-side manifest (required)
├── README.md             # App documentation (optional, used by official examples)
├── assets/               # Optional: static web frontend served by the WebUI Brick
│   ├── index.html
│   ├── app.js
│   └── style.css
├── python/
│   ├── main.py           # Python entry point (required)
│   └── requirements.txt  # pip deps (auto-installed on run; needs network on the board)
└── sketch/
    ├── sketch.ino         # Arduino sketch (required)
    └── sketch.yaml        # MCU build config (required)
```
Filenames and directory names are fixed — the runtime looks for them exactly. Required: `app.yaml`, `python/main.py`, `sketch/sketch.ino`, `sketch/sketch.yaml`. Everything else is optional. Some examples add extra Python modules under `python/` (e.g. `store.py`) and a `data/` directory for persisted state.

### app.yaml
Declares project metadata and lists Bricks. **Most** Bricks run as Docker containers on the MPU (not necessarily all).
```yaml
name: My App
description: "What it does"
version: "1.0.0"
ports: []
bricks: []   # App Lab populates this when you add Bricks via UI
```
- Arduino's docs say `app.yaml` "cannot be edited" *inside App Lab* (the GUI manages it) *(documented)*. Hand-editing over the CLI/SSH is a separate matter — if you do it, be careful, and expect App Lab to possibly rewrite it.

### python/main.py boilerplate
```python
from arduino.app_utils import App, Bridge
import time

def loop():
    time.sleep(1)
    result = Bridge.call("my_mcu_func", arg1, arg2)

App.run(user_loop=loop)  # required — starts Bridge and event loop
```
- `arduino.app_utils` is pre-installed on the board.
- `App.run()` is mandatory; don't run as a plain script.
- Use `Bridge.on("func_name", handler)` to receive notifications from the MCU.
- **API version caveat:** this file uses `from arduino.app_utils import App, Bridge` (capitalized), which matches current example repos. An earlier tutorial used the lowercase style `from arduino import app, bridge` and top-level Brick imports like `from webui_html import WebUI`. If imports fail, the API may have changed between App Lab versions — check the Brick API reference in App Lab and the official `arduino/app-bricks-examples` repo.

### Clean shutdown for non-Brick resources *(observed)*
`App.run()` only auto-stops registered **Bricks** (anything using the `@brick` decorator,
e.g. `VideoObjectDetection`, `WebUI`). Plain objects that hold external state -
LEGO motors/sensors via `legoeducation.py`/`lelib`, raw sockets, file handles - are
never touched on shutdown unless you do it yourself.

`arduino-app-cli app stop` sends SIGTERM. `App.run()` catches it, then always calls
`sys.exit(exit_code)` - which raises `SystemExit` and unwinds the stack. Because of
this:
- Code placed **after** `App.run(...)` never executes on a normal stop (SystemExit
  propagates out of the `App.run()` call itself).
- A `try/finally` **wrapping** the `App.run(...)` call *does* still run - `finally`
  fires while `SystemExit` unwinds through it.

```python
try:
    App.run(user_loop=loop)
finally:
    motor.movement_move_tank(0, 0)  # stop before releasing
    motor.disconnect()
```
Use this pattern for anything with a lifecycle that isn't a Brick. This behavior comes from testing rather than public docs, so re-verify after App Lab updates.

### sketch/sketch.ino boilerplate
```cpp
#include "Arduino_RouterBridge.h"

bool my_mcu_func(bool state) {
    digitalWrite(LED_BUILTIN, state ? LOW : HIGH);
    return state;
}

void setup() {
    Bridge.begin();                          // required
    Bridge.provide("my_mcu_func", my_mcu_func);  // expose to Python
}

void loop() {
    // Bridge.update() is handled automatically
    // Some community examples add a small delay(10) here; an empty loop() has
    // not been observed to cause problems, but add a short delay if the MCU
    // seems to starve other work.
}
```
- `Bridge.begin()` in `setup()` is mandatory.
- `Bridge.provide()` registers functions Python can call via `Bridge.call()`.
- `Bridge.provide_safe()` variant is thread-safe (called from main loop thread via `update_safe()`) *(observed)*.
- RGB LEDs 1-2 are MPU-controlled (active low); LEDs 3-4 are MCU-controlled *(observed)*.

### sketch/sketch.yaml
```yaml
profiles:
  default:
    fqbn: arduino:zephyr:unoq
    platforms:
      - platform: arduino:zephyr
    libraries:
      - MsgPack (0.4.2)       # RouterBridge dependency
      - DebugLog (0.8.4)
      - ArxContainer (0.7.0)
      - ArxTypeTraits (0.3.1)
      # Add other libraries here, spelling must be exact
default_profile: default
```
Check exact library names in App Lab's library manager before adding.

### Bridge API summary
| Side | Call | Effect |
|------|------|--------|
| Python | `Bridge.call("func", args...)` | Synchronous RPC to MCU; blocks until response |
| Python | `Bridge.on("func", handler)` | Register handler for MCU notifications |
| Sketch | `Bridge.provide("func", fn)` | Expose function to Python |
| Sketch | `Bridge.call("func", args...).result(var)` | Synchronous RPC to Python |
| Sketch | `Bridge.notify("func", args...)` | Fire-and-forget to Python |

RPC round-trip latency ~8 ms *(observed, not documented)*.

### Bricks
Pre-packaged services (AI vision, web UI, time-series DB, etc.), mostly Docker containers, declared in `app.yaml` and imported in Python. Each Brick has API docs and usage examples in App Lab's **Bricks** tab.
```python
from arduino.app_bricks.web_ui import WebUI
from arduino.app_bricks.video_objectdetection import VideoObjectDetection
ui = WebUI()  # serves on port 7000 by default
```
First run downloads container images (needs internet); subsequent runs use cache.

Bricks seen in official examples and community projects (check App Lab's Bricks tab for the current list and exact import paths):

| Brick | Purpose | Import path |
|-------|---------|-------------|
| `web_ui` | Web server + HTTP API endpoints; serves `assets/` frontend | `arduino.app_bricks.web_ui` |
| `video_objectdetection` | Camera object detection | `arduino.app_bricks.video_objectdetection` |
| `video_image_classification` | MobileNet-style image classification (e.g. "person" model) | verify in App Lab |
| `dbstorage_sqlstore` | SQLite persistence (often added implicitly, e.g. by the LED matrix example) | verify in App Lab |
| Audio classification | Sound classification | verify in App Lab |

Some examples call external AI provider APIs and need an internet connection plus an API key (e.g. Google AI Studio).

### WebUI notes
- The app is reachable in a browser at `<board-ip>:7000`.
- Static frontends go in `assets/` (`index.html`, `app.js`, `style.css`).
- Official examples (e.g. the LED matrix painter) use the WebUI Brick to expose HTTP API endpoints (FastAPI-style routes such as `/persist_frame`, `/load_frame`, `/list_frames`) that the frontend calls, with Python bridging to the MCU via `Bridge.call`.
- Exact route-registration API: check the WebUI Brick's API reference in App Lab, or `arduino/app-bricks-examples`.

### LED matrix
- Onboard matrix is 8×13.
- `arduino.app_utils` provides `Frame` and `FrameDesigner` helpers used by the official LED matrix painter example (which also subclasses `Frame` for serialization and animation). Sketch side receives frame data through Bridge RPC.
- See `arduino/app-bricks-examples` (LED matrix painter) for a full working reference.

### Hardware access and gotchas
- **Qwiic / Modulino sensors**: connect over the Qwiic (I2C) connector; official examples exist for Modulino Movement (vibration/anomaly detection).
- **SPI from the MPU side**: `/dev/spidev0.0` needs correct group permissions (a udev-style rule granting the `gpiod` group access). Without it, expect `PermissionError` or empty data. Check with `ls -l /dev/spidev0.0`.
- **Custom Bricks**: the community SPI bridge project shows a custom Brick layout (its own container, `brick_compose.yaml`, Dockerfile, and `__init__.py`) and uses `docker compose watch` to auto-rebuild on changes. Niche, but a useful template.
- **Network**: `requirements.txt` installs and container pulls happen on the board and need connectivity.

### Debugging and failure modes
- In App Lab's GUI there are two console tabs: **Main (Python)** shows Python `print()` output; **Sketch (Microcontroller)** shows serial output from the sketch (`Serial`; never `Serial1`).
- An app can launch successfully without actually working *(documented)*. Check **both** console tabs, not just whether the Run button changed state.
- From the CLI, use `arduino-app-cli app logs` (see below). CLI-side, Python logs go to a log file rather than stdout *(observed)*.

### Running / deploying
```bash
# Via App Lab GUI: press Run button
# Via CLI on the board:
arduino-app-cli app start ~/ArduinoApps/my_app
arduino-app-cli app logs  ~/ArduinoApps/my_app
arduino-app-cli app stop  ~/ArduinoApps/my_app
```
Apps live in `~/ArduinoApps/` on the board.
