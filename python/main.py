"""UNO Q side: park the car so the minifig sits at the center of the laptop's view.

Receives detections from laptop/detect.py over MQTT and runs a PD-controller on
the horizontal error (cx - 0.5), sending wheel speeds to the sketch's drive().
Stops when data is stale or the minifig is lost. With MOTOR_TEST on, it instead
pulses the motors forward/back to check wiring.
"""

import json
import threading
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import App, Bridge, Logger

# Must match laptop/detect.py
BROKER = "test.mosquitto.org"
PORT = 1883
TOPIC = "dchoate119/d2d/detection"

STALE_AFTER = 0.3  # seconds without a message before the car must stop

# Control tuning. u = KP * err + KD * derr, err = cx - 0.5, derr = d(err)/dt
# speed = DIRECTION * sign(u) * (MIN_SPEED + |u|)
DIRECTION = -1     # flip sign if the car drives away from center instead of toward it
KP = 250           # speed per unit of error (err of 0.1 -> +10)
KD = 1.5            # speed per unit of error rate (derr of 0.2/s -> +4); raise if it overshoots
D_ALPHA = 0.3      # derivative low-pass, 0..1; lower = smoother but laggier
MIN_SPEED = 40     # smallest speed that actually moves the car
MAX_SPEED = 100    # 0..255 cap
DEADBAND = 0.012    # |err| below this ...
PARK_RATE = 100   # ... and |derr| below this (per second) counts as parked
CONTROL_HZ = 20

MOTOR_TEST = False  # pulse the motors instead of running the controller
TEST_SPEED = 120    # 0..255; keep low for a bench test

logger = Logger("door-to-door")

latest = None          # last decoded message
latest_rx = 0.0        # time.monotonic() when it arrived
rx_count = 0
prev_err = None        # err from the previous detection, None after a reset
derr = 0.0             # filtered d(err)/dt, updated per detection
lock = threading.Lock()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        logger.warning(f"MQTT connect failed: {reason_code}")
        return
    logger.info(f"MQTT connected to {BROKER}, subscribing to {TOPIC}")
    client.subscribe(TOPIC, qos=0)  # (re)subscribe on every reconnect


def update_derivative(data, now):
    """Filtered d(err)/dt over detections (not control ticks). Caller holds lock."""
    global prev_err, derr
    gap = now - latest_rx
    if not data.get("found") or gap > STALE_AFTER:
        prev_err, derr = None, 0.0  # don't differentiate across a dropout
        if not data.get("found"):
            return
    err = data["cx"] - 0.5
    if prev_err is not None and gap > 0:
        derr += D_ALPHA * ((err - prev_err) / gap - derr)
    prev_err = err


def on_message(client, userdata, msg):
    global latest, latest_rx, rx_count
    try:
        data = json.loads(msg.payload)
    except ValueError:
        logger.warning(f"Bad payload: {msg.payload[:80]!r}")
        return
    now = time.monotonic()
    with lock:
        update_derivative(data, now)
        latest = data
        latest_rx = now
        rx_count += 1


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect_async(BROKER, PORT)  # retries in the background if the network isn't up yet
client.loop_start()


def drive(left, right):
    Bridge.call("drive", int(left), int(right))


def hold(left, right, seconds):
    """Repeat a drive command so the sketch's 300 ms watchdog stays fed."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        drive(left, right)
        time.sleep(0.1)


def motor_test():
    logger.info(f"forward {TEST_SPEED}")
    hold(TEST_SPEED, TEST_SPEED, 1.0)
    drive(0, 0)
    time.sleep(1.0)
    logger.info(f"reverse {TEST_SPEED}")
    hold(-TEST_SPEED, -TEST_SPEED, 1.0)
    drive(0, 0)
    logger.info("stop")
    time.sleep(3.0)


def control_speed(cx, d):
    """1D PD-control. Returns a signed speed for both wheels (steering can split this later)."""
    err = cx - 0.5
    if abs(err) < DEADBAND and abs(d) < PARK_RATE:
        return 0
    u = KP * err + KD * d  # D term can flip u's sign near center to brake
    if u == 0:
        return 0
    magnitude = min(MIN_SPEED + abs(u), MAX_SPEED)
    return DIRECTION * magnitude * (1 if u > 0 else -1)


last_log = 0.0


def loop():
    """One control step: read the latest detection, compute speed, drive."""
    global rx_count, last_log
    if MOTOR_TEST:
        motor_test()
        return
    time.sleep(1.0 / CONTROL_HZ)

    with lock:
        data, age, d = latest, time.monotonic() - latest_rx, derr

    if data is None or age > STALE_AFTER:
        speed, status = 0, "STALE"
    elif not data.get("found"):
        speed, status = 0, "no minifig"
    else:
        speed = control_speed(data["cx"], d)
        status = f"cx={data['cx']:.3f} err={data['cx'] - 0.5:+.3f} derr={d:+.3f}/s"
        if speed == 0:
            status += " PARKED"
    drive(speed, speed)

    now = time.monotonic()
    if now - last_log >= 1.0:
        with lock:
            count, rx_count = rx_count, 0
        logger.info(f"{status}  speed={speed:+.0f}  {count} msg/s")
        last_log = now


App.run(user_loop=loop)
