# 😀 door-to-door-service

### Description

An Arduino UNO Q car that parks itself so a green minifig sits at the center of a laptop webcam's view. The laptop detects the minifig with a YOLOv8n model and publishes its position over MQTT; the UNO Q turns that into motor commands. Motion is 1D (left/right on screen) for now, with steering planned.

### System layout

```
 Laptop webcam
      │
      ▼
 laptop/detect.py        Laptop     YOLOv8n finds the minifig
      │  MQTT
      ▼
 python/main.py          UNO Q MPU  P-control on cx, stop on timeout
      │  Bridge
      ▼
 sketch/sketch.ino       UNO Q MCU  PWM to Cytron Maker Drive
      │
      ▼
 2 motors
```

| Link | Details |
|---|---|
| MQTT | Broker `test.mosquitto.org` for now (local Mosquitto later). Topic `dchoate119/d2d/detection`. Payload `{t, found, cx, cy, w, h, conf}`, coordinates normalized 0–1. Goal: `cx = 0.5` |
| Bridge | `drive(left, right)`, speeds −255..255 |

### Project structure

```
app.yaml                 UNO Q app manifest
python/main.py           UNO Q: MQTT subscriber + control loop
sketch/sketch.ino        UNO Q MCU: motor driver
laptop/detect.py         Laptop: webcam detection + MQTT publish
laptop/models/           Trained YOLOv8n weights
laptop/requirements.txt  Laptop Python deps
```

### Running

```bash
# Laptop
pip install -r laptop/requirements.txt
python laptop/detect.py --mqtt [--device gpu]

# UNO Q
arduino-app-cli app start ~/ArduinoApps/door-to-door-service
```

### Progress

- [x] Train YOLOv8n minifig model
- [x] Laptop detection (~30 fps GPU, ~25 fps CPU)
- [x] Publish detections over MQTT (public broker)
- [x] UNO Q subscribes and logs detections
- [x] Sketch + Bridge: drive motors through the Maker Drive
- [x] Close the loop: PD-control on `cx`, timeout stop, tuning
