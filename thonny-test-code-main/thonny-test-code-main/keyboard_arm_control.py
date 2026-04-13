from machine import Pin, PWM
import time
import sys

# Servo PWM settings
SERVO_FREQ = 50    # 50Hz for standard servos
MIN_US = 500       # 0° pulse width (default servos)
MAX_US = 2500      # 180° pulse width (default servos)
GRIPPER_MIN_US = 500   # Custom gripper close position (adjust as needed)
GRIPPER_MAX_US = 2500  # Custom gripper open position (adjust as needed)

# Servo-to-GPIO mapping (GP16-GP21)
servo_pins = {
    "base": 16,        # GP16 (Pin 21)
    "shoulder": 17,    # GP17 (Pin 22)
    "elbow": 18,       # GP18 (Pin 24)
    "wrist_pitch": 19, # GP19 (Pin 25)
    "wrist_roll": 20,  # GP20 (Pin 26)
    "gripper": 21      # GP21 (Pin 27)
}

# Initialize PWM objects for all servos
servos = {}
for name, pin in servo_pins.items():
    pwm = PWM(Pin(pin))
    pwm.freq(SERVO_FREQ)
    servos[name] = {"pwm": pwm, "angle": 90}  # Start at neutral position

def angle_to_duty(angle, name):
    """Convert angle to duty cycle with gripper-specific handling"""
    if name == "gripper":
        pulse_width = GRIPPER_MIN_US + (GRIPPER_MAX_US - GRIPPER_MIN_US) * angle / 180
    else:
        pulse_width = MIN_US + (MAX_US - MIN_US) * angle / 180
    return int(pulse_width * 65535 / 20000)  # 20ms period

def set_servo(name, angle):
    """Move servo to specified angle (0-180)"""
    angle = max(0, min(180, angle))  # Constrain angle
    servos[name]["pwm"].duty_u16(angle_to_duty(angle, name))
    servos[name]["angle"] = angle
    print(f"{name:12} → {angle}°")

def move_servo(name, delta):
    """Move servo by delta degrees"""
    set_servo(name, servos[name]["angle"] + delta)

# Keyboard control mapping
key_map = {
    "q": lambda: move_servo("base", 5),
    "a": lambda: move_servo("base", -5),
    "w": lambda: move_servo("shoulder", 5),
    "s": lambda: move_servo("shoulder", -5),
    "e": lambda: move_servo("elbow", 5),
    "d": lambda: move_servo("elbow", -5),
    "r": lambda: move_servo("wrist_pitch", 5),
    "f": lambda: move_servo("wrist_pitch", -5),
    "t": lambda: move_servo("wrist_roll", 5),
    "g": lambda: move_servo("wrist_roll", -5),
    "y": lambda: move_servo("gripper", 10),  # Larger step for gripper
    "h": lambda: move_servo("gripper", -10),
}

# Main control loop
print("\nRobotic Arm Control Initialized")
print("Controls:")
print("Q/A - Base | W/S - Shoulder | E/D - Elbow")
print("R/F - Wrist Pitch | T/G - Wrist Roll | Y/H - Gripper")
print("CTRL+C to exit\n")

try:
    # Center all servos on startup (gripper at 0°)
    for name in servos:
        set_servo(name, 90 if name != "gripper" else 0)
    
    while True:
        key = sys.stdin.read(1).lower()
        if key in key_map:
            key_map[key]()
        elif key == "\x03":  # CTRL+C
            break
            
except KeyboardInterrupt:
    print("\nShutting down...")
finally:
    # Cleanup
    for s in servos.values():
        s["pwm"].deinit()
    print("All servos disabled")