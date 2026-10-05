"""UNO Q side: receive minifig detections from the laptop over MQTT.

For now this only logs what arrives and flags stale data. Motor control
(Bridge.call("drive", left, right)) comes next.
"""

import json
import threading
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import App, Logger

# Must match laptop/detect.py
BROKER = "test.mosquitto.org"
PORT = 1883
TOPIC = "dchoate119/d2d/detection"

STALE_AFTER = 0.3  # seconds without a message before the car must stop

logger = Logger("door-to-door")

latest = None          # last decoded message
latest_rx = 0.0        # time.monotonic() when it arrived
rx_count = 0
lock = threading.Lock()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        logger.warning(f"MQTT connect failed: {reason_code}")
        return
    logger.info(f"MQTT connected to {BROKER}, subscribing to {TOPIC}")
    client.subscribe(TOPIC, qos=0)  # (re)subscribe on every reconnect


def on_message(client, userdata, msg):
    global latest, latest_rx, rx_count
    try:
        data = json.loads(msg.payload)
    except ValueError:
        logger.warning(f"Bad payload: {msg.payload[:80]!r}")
        return
    with lock:
        latest = data
        latest_rx = time.monotonic()
        rx_count += 1


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect_async(BROKER, PORT)  # retries in the background if the network isn't up yet
client.loop_start()


def loop():
    """Report once per second: message rate, freshness, and the latest detection."""
    global rx_count
    time.sleep(1.0)
    with lock:
        data, age, count = latest, time.monotonic() - latest_rx, rx_count
        rx_count = 0

    if data is None or age > STALE_AFTER:
        logger.info(f"STALE ({count} msg/s)  -> would stop")
    elif not data.get("found"):
        logger.info(f"no minifig ({count} msg/s)  -> would stop")
    else:
        lag = time.time() - data["t"]  # only meaningful if both clocks are NTP-synced
        logger.info(f"cx={data['cx']:.3f}  err={data['cx'] - 0.5:+.3f}  "
                    f"conf={data['conf']:.2f}  {count} msg/s  lag~{lag * 1000:.0f} ms")


App.run(user_loop=loop)
