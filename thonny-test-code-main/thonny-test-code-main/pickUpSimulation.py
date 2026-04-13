from machine import Pin, PWM
import time

# Servo Configuration
SERVO_FREQ = 50
servo_pins = {
    "base": 16, "shoulder": 17, "elbow": 18,
    "wrist_pitch": 19, "wrist_roll": 20, "gripper": 21
}

# Initialize servos
servos = {name: PWM(Pin(pin)) for name, pin in servo_pins.items()}
for s in servos.values():
    s.freq(SERVO_FREQ)

# Movement parameters
STEP_DELAY = 0.02      # Delay between each small step (in seconds) — smaller = faster
INTERPOLATION_STEP = 3 # Degrees to move per step (smaller = smoother & slower)
GRIPPER_OPEN = 180
GRIPPER_CLOSE = 0

# Current angles (track current position for smooth motion)
current_angles = {
    "base": 90, "shoulder": 90, "elbow": 90,
    "wrist_pitch": 90, "wrist_roll": 90, "gripper": GRIPPER_OPEN
}

def set_servo(name, angle):
    """Set servo to angle (0–180) by converting to duty cycle in nanoseconds"""
    # Convert angle to pulse width (500–2500 µs) → then to nanoseconds
    pulse_us = 500 + (angle / 180.0) * 2000
    pulse_ns = int(pulse_us * 1000)
    servos[name].duty_ns(pulse_ns)

def move_servo_smooth(name, target_angle, step=INTERPOLATION_STEP, delay=STEP_DELAY):
    """Gradually move servo from current to target angle"""
    global current_angles
    current = current_angles[name]
    
    # Determine direction
    step_size = step if target_angle > current else -step
    
    for angle in range(int(current), int(target_angle), step_size):
        set_servo(name, angle)
        time.sleep(delay)
    
    # Final adjustment to ensure exact target
    set_servo(name, target_angle)
    current_angles[name] = target_angle

def move_servos_smooth(positions, step=INTERPOLATION_STEP, delay=STEP_DELAY):
    """Move multiple servos smoothly to target positions"""
    for name, target in positions.items():
        move_servo_smooth(name, target, step, delay)

def pick_and_place():
    print("Moving to home position...")
    move_servos_smooth({
        "base": 90, "shoulder": 90, "elbow": 90,
        "wrist_pitch": 90, "wrist_roll": 90, "gripper": GRIPPER_OPEN
    }, step=2, delay=0.03)

    time.sleep(1.0)

    # === PICK SEQUENCE ===
    print("Moving to pick position...")
    move_servos_smooth({"base": 60}, step=2, delay=0.03)
    move_servos_smooth({"shoulder": 60, "elbow": 120}, step=2, delay=0.03)
    move_servos_smooth({"wrist_pitch": 45}, step=2, delay=0.03)

    print("Picking object...")
    move_servos_smooth({"gripper": GRIPPER_CLOSE}, delay=0.05)  # Slow grip
    time.sleep(2.0)  # Hold grip

    # === LIFT OBJECT ===
    print("Lifting...")
    move_servos_smooth({"shoulder": 80, "elbow": 100, "wrist_pitch": 70}, step=2, delay=0.03)

    # === ROTATE TO PLACE POSITION ===
    print("Rotating to place position...")
    move_servos_smooth({"base": 120}, step=2, delay=0.03)

    # === PLACE OBJECT ===
    print("Placing...")
    move_servos_smooth({"shoulder": 100, "elbow": 80, "wrist_pitch": 110}, step=2, delay=0.03)
    move_servos_smooth({"gripper": GRIPPER_OPEN}, delay=0.05)
    time.sleep(2.0)

    # === RETURN HOME ===
    print("Returning to home...")
    move_servos_smooth({
        "base": 90, "shoulder": 90, "elbow": 90,
        "wrist_pitch": 90, "wrist_roll": 90
    }, step=2, delay=0.03)

# Run the sequence
print("Starting smooth pick-and-place demo...")
try:
    while True:
        pick_and_place()
        time.sleep(3)  # Pause between cycles
except KeyboardInterrupt:
    print("Demo stopped")
finally:
    # Turn off all servos
    for s in servos.values():
        s.deinit()