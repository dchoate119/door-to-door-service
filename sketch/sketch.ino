// door-to-door-service: drive 2 motors through a Cytron Maker Drive.
//
// Python calls drive(left, right) over the Bridge with speeds -255..255.
// If no command arrives for WATCHDOG_MS, both motors stop.
//
// Maker Drive logic per motor: A=PWM,B=0 forward; A=0,B=PWM reverse; both 0 coast.

#include "Arduino_RouterBridge.h"

// Wiring: Maker Drive input -> UNO Q pin (all PWM-capable)
const int M1A = 3;
const int M1B = 5;
const int M2A = 6;
const int M2B = 9;

// Flip if a motor spins the wrong way for a positive speed
const bool INVERT_M1 = false;
const bool INVERT_M2 = false;

const unsigned long WATCHDOG_MS = 300;

unsigned long last_cmd_ms = 0;
bool stopped = true;

void set_motor(int pin_a, int pin_b, int speed, bool invert) {
    speed = constrain(speed, -255, 255);
    if (invert) speed = -speed;
    // analogWrite only (no digitalWrite) so the pins stay in PWM mode
    analogWrite(pin_a, speed > 0 ? speed : 0);
    analogWrite(pin_b, speed < 0 ? -speed : 0);
}

void stop_motors() {
    set_motor(M1A, M1B, 0, false);
    set_motor(M2A, M2B, 0, false);
    stopped = true;
}

// Exposed to Python: left -> motor 1, right -> motor 2
void drive(int left, int right) {
    set_motor(M1A, M1B, left, INVERT_M1);
    set_motor(M2A, M2B, right, INVERT_M2);
    last_cmd_ms = millis();
    stopped = (left == 0 && right == 0);
}

void setup() {
    Monitor.begin(115200);
    stop_motors();

    Bridge.begin();
    // provide_safe runs drive() in the loop thread, so it never races the watchdog
    Bridge.provide_safe("drive", drive);
    Monitor.println("door-to-door: motors ready");
}

void loop() {
    if (!stopped && millis() - last_cmd_ms > WATCHDOG_MS) {
        stop_motors();
        Monitor.println("watchdog: no drive command, motors stopped");
    }
}
