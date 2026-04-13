# main.py - 6-DOF Robotic Arm Controller (Same Pin Mapping as Working Code)
from machine import Pin, PWM
import time
import sys
import select  # For non-blocking input

# ===== SERVO PWM SETTINGS =====
SERVO_FREQ = 50           # Standard 50Hz for servos
MIN_US = 500              # 0° pulse width
MAX_US = 2500             # 180° pulse width
GRIPPER_MIN_US = 500      # ← Customize: closed position
GRIPPER_MAX_US = 2400     # ← Customize: open position (reduce if needed)

# ===== GPIO PIN MAPPING (EXACT SAME AS WORKING CODE) =====
servo_pins = {
    "base": 16,        # GP16 → Pin 21
    "shoulder": 17,    # GP17 → Pin 22
    "elbow": 25,       # GP25 → Different from your main.py!
    "wrist_roll": 20,  # GP20 → Pin 26
    "wrist_pitch": 22, # GP22 → Different from your main.py!
    "gripper": 26      # GP26 → Different from your main.py!
}

# Initialize PWM for all servos
servos = {}
for name, pin in servo_pins.items():
    pwm = PWM(Pin(pin))
    pwm.freq(SERVO_FREQ)
    servos[name] = {"pwm": pwm, "angle": 90}  # Start at neutral

# ===== HELPER FUNCTIONS =====
def angle_to_duty(angle, name):
    """Convert angle to duty cycle (u16), with gripper-specific range"""
    if name == "gripper":
        pulse_width = GRIPPER_MIN_US + (GRIPPER_MAX_US - GRIPPER_MIN_US) * angle / 180
    else:
        pulse_width = MIN_US + (MAX_US - MIN_US) * angle / 180
    return int(pulse_width * 65535 / 20000)  # 20ms = 20000 µs

def set_servo(name, angle):
    """Set servo to angle (0–180°), clamp and update"""
    angle = max(0, min(180, angle))
    duty = angle_to_duty(angle, name)
    servos[name]["pwm"].duty_u16(duty)
    servos[name]["angle"] = angle
    print(f"{name:12} → {angle}°")

def move_servo(name, delta):
    """Move servo by delta degrees"""
    new_angle = servos[name]["angle"] + delta
    set_servo(name, new_angle)

# ===== COMMAND HANDLER =====
def handle_command(cmd):
    cmd = cmd.strip().upper()

    # Shoulder
    if cmd == 'U':
        move_servo('shoulder', 5)
        return f"SHOULDER:{servos['shoulder']['angle']}°"
    elif cmd == 'D':
        move_servo('shoulder', -5)
        return f"SHOULDER:{servos['shoulder']['angle']}°"

    # Base
    elif cmd == 'A':
        move_servo('base', 5)
        return f"BASE:{servos['base']['angle']}°"
    elif cmd == 'S':
        move_servo('base', -5)
        return f"BASE:{servos['base']['angle']}°"

    # Elbow
    elif cmd == 'E':
        move_servo('elbow', 5)
        return f"ELBOW:{servos['elbow']['angle']}°"
    elif cmd == 'F':
        move_servo('elbow', -5)
        return f"ELBOW:{servos['elbow']['angle']}°"

    # Wrist Pitch
    elif cmd == 'I':
        move_servo('wrist_pitch', 5)
        return f"WPI:{servos['wrist_pitch']['angle']}°"
    elif cmd == 'K':
        move_servo('wrist_pitch', -5)
        return f"WPI:{servos['wrist_pitch']['angle']}°"

    # Wrist Roll
    elif cmd == 'J':
        move_servo('wrist_roll', 5)
        return f"WRO:{servos['wrist_roll']['angle']}°"
    elif cmd == 'L':
        move_servo('wrist_roll', -5)
        return f"WRO:{servos['wrist_roll']['angle']}°"

    # Gripper
    elif cmd == 'C':
        set_servo('gripper', 90)  # Open
        return "GRIPPER:CLOSED:90°"
    elif cmd == 'O':
        set_servo('gripper', 0)   # Close
        return "GRIPPER:OPEN:0°"

    # Emergency stop
    elif cmd == 'X':
        set_servo('base', 90)
        set_servo('shoulder', 95)  # Return to custom safe position
        set_servo('elbow', 170)    # Return to custom safe position
        set_servo('wrist_pitch', 90)
        set_servo('wrist_roll', 180)  # ← Fixed: 180° like your working code
        set_servo('gripper', 0)
        return "EMERGENCY:SAFE_POSITION"

    # Status
    elif cmd == '?':
        return ", ".join(f"{k}:{v['angle']}°" for k, v in servos.items())

    else:
        return f"ERROR:INVALID_CMD:'{cmd}'"

# ===== INITIALIZATION =====
def setup_arm():
    print("🤖 Initializing 6-DOF Robot Arm...")
    # Start in custom safe position (EXACT SAME AS WORKING CODE)
    set_servo('base', 90)
    set_servo('shoulder', 95)  # Custom shoulder position
    set_servo('elbow', 170)    # Custom elbow position
    set_servo('wrist_pitch', 90)
    set_servo('wrist_roll', 180)  # ← This was 90° in emergency stop, now 180° for init
    set_servo('gripper', 0)    # Gripper closed
    time.sleep(0.5)
    print("✅ Arm ready!")

# ===== MAIN LOOP =====
setup_arm()

print("""
🎮 6-DOF Robotic Arm Controller
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Controls:
U/D = Shoulder | A/S = Base (Left/Right)
E/F = Elbow    | I/K = Wrist Pitch (Up/Down)
J/L = Wrist Roll (Left/Right)
C = Open Gripper | O = Close Gripper
X = Emergency Stop | ? = Get Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

# Setup non-blocking serial input
poll_obj = select.poll()
poll_obj.register(sys.stdin, select.POLLIN)

# Main loop
while True:
    if poll_obj.poll(10):  # 10ms timeout
        try:
            cmd = sys.stdin.readline()
            response = handle_command(cmd)
            print(f"💡 {response}")
        except Exception as e:
            print(f"❌ Error: {e}")
    time.sleep(0.01)
