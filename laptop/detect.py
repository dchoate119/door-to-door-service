"""Run the minifig YOLOv8 model on the laptop webcam and show where it is.

Runs on the LAPTOP, not the UNO Q. Draws the best detection, the screen
center line, and the horizontal error the car will eventually drive to zero.
With --mqtt, also publishes every frame's detection as JSON for the car.

    python laptop/detect.py                    # uses the only .pt in laptop/models/
    python laptop/detect.py --device gpu       # CUDA instead of the default cpu
    python laptop/detect.py --model laptop/models/best.pt --camera 0 --imgsz 640
    python laptop/detect.py --mqtt             # publish to broker on localhost

Press q (or Esc) in the preview window to quit.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

MODELS_DIR = Path(__file__).parent / "models"
TOPIC = "d2d/detection"


def find_model(path):
    if path:
        return Path(path)
    candidates = sorted(MODELS_DIR.glob("*.pt"))
    if len(candidates) != 1:
        raise SystemExit(
            f"Expected exactly one .pt in {MODELS_DIR}, found {len(candidates)}. "
            "Pass --model explicitly."
        )
    return candidates[0]


def best_detection(result, frame_w, frame_h):
    """Return the highest-confidence box as a normalized dict, or None."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return None
    i = int(boxes.conf.argmax())
    x1, y1, x2, y2 = boxes.xyxy[i].tolist()
    return {
        "cx": (x1 + x2) / 2 / frame_w,
        "cy": (y1 + y2) / 2 / frame_h,
        "w": (x2 - x1) / frame_w,
        "h": (y2 - y1) / frame_h,
        "conf": float(boxes.conf[i]),
        "cls": result.names[int(boxes.cls[i])],
        "xyxy": (int(x1), int(y1), int(x2), int(y2)),
    }


def connect_mqtt(host, port):
    import paho.mqtt.client as mqtt  # only needed with --mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="d2d-laptop")
    client.connect(host, port)
    client.loop_start()
    print(f"MQTT: publishing to {host}:{port} topic '{TOPIC}'")
    return client


def to_message(det):
    """JSON payload for the car. Coordinates are normalized 0..1."""
    msg = {"t": time.time(), "found": det is not None}
    if det:
        msg.update({k: round(det[k], 4) for k in ("cx", "cy", "w", "h", "conf")})
    return json.dumps(msg)


def draw(frame, det, fps):
    h, w = frame.shape[:2]
    cv2.line(frame, (w // 2, 0), (w // 2, h), (255, 255, 0), 1)
    if det:
        x1, y1, x2, y2 = det["xyxy"]
        cx_px = int(det["cx"] * w)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.line(frame, (cx_px, 0), (cx_px, h), (0, 255, 0), 1)
        label = f"{det['cls']} {det['conf']:.2f}  err={det['cx'] - 0.5:+.3f}"
        cv2.putText(frame, label, (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    else:
        cv2.putText(frame, "no detection", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(frame, f"{fps:.1f} fps", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="path to .pt (default: only .pt in laptop/models/)")
    ap.add_argument("--camera", type=int, default=0, help="webcam index")
    ap.add_argument("--imgsz", type=int, default=640, help="inference size; try 320 if slow")
    ap.add_argument("--conf", type=float, default=0.5, help="minimum confidence")
    ap.add_argument("--device", choices=["cpu", "gpu"], default="cpu",
                    help="run inference on cpu (default) or the first CUDA gpu")
    ap.add_argument("--mqtt", action="store_true", help="publish detections over MQTT")
    ap.add_argument("--broker", default="localhost", help="MQTT broker host")
    ap.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    args = ap.parse_args()
    device = "0" if args.device == "gpu" else "cpu"  # ultralytics device names

    mqtt_client = connect_mqtt(args.broker, args.port) if args.mqtt else None

    model_path = find_model(args.model)
    model = YOLO(str(model_path))
    print(f"Model: {model_path}  classes: {model.names}  device: {args.device}")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {args.camera}")

    fps = 0.0
    last = time.perf_counter()
    last_print = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Camera read failed")
                break
            h, w = frame.shape[:2]
            result = model.predict(frame, imgsz=args.imgsz, conf=args.conf,
                                   device=device, verbose=False)[0]
            det = best_detection(result, w, h)
            if mqtt_client:
                mqtt_client.publish(TOPIC, to_message(det), qos=0)

            now = time.perf_counter()
            inst_fps = 1.0 / max(now - last, 1e-6)
            fps = 0.9 * fps + 0.1 * inst_fps if fps else inst_fps  # smoothed
            last = now

            if now - last_print > 0.5:
                last_print = now
                if det:
                    print(f"{fps:5.1f} fps  cx={det['cx']:.3f}  err={det['cx'] - 0.5:+.3f}  "
                          f"w={det['w']:.3f}  conf={det['conf']:.2f}")
                else:
                    print(f"{fps:5.1f} fps  no detection")

            draw(frame, det, fps)
            cv2.imshow("door-to-door detect", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        if mqtt_client:
            mqtt_client.publish(TOPIC, to_message(None), qos=0)  # tell the car to stop
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
