# robot_arm_pico.py - 6-DOF Robotic Arm Controller with Position Sequence
from machine import Pin, PWM
import time
import sys
import select  # For non-blocking input

# ===== SERVO PWM SETTINGS =====
SERVO_FREQ = 50  # Standard 50Hz for servos
MIN_US = 500  # 0° pulse width
MAX_US = 2500  # 180° pulse width
GRIPPER_MIN_US = 500  # ← Customize: closed position
GRIPPER_MAX_US = 2400  # ← Customize: open position (reduce if needed)

# ===== GPIO PIN MAPPING (GP16 to GP21) =====
servo_pins = {
    "base": 16,  # GP16 → Pin 21
    "shoulder": 17,  # GP17 → Pin 22
    "elbow": 25,  # GP18 → Pin 24
    "wrist_roll": 20,  # GP20 → Pin 22
    "wrist_pitch": 22,  # GP19 → Pin 20
    "gripper": 26  # GP21 → Pin 26
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


def set_servo_smooth(name, target_angle, steps=10, delay=0.1):
    """Move servo smoothly to target angle - FIXED LOGIC"""
    current_angle = servos[name]["angle"]
    # Calculate the actual step needed
    if current_angle == target_angle:
        return

    step_size = (target_angle - current_angle) / steps

    for step in range(steps):
        new_angle = current_angle + (step_size * (step + 1))
        set_servo(name, round(new_angle))  # Round to avoid floating point issues
        time.sleep(delay)


def move_servo(name, delta):
    """Move servo by delta degrees"""
    new_angle = servos[name]["angle"] + delta
    set_servo(name, new_angle)


def move_to_position_29_29():
    """Automatically move arm to touch position (29, 29)"""
    print("🚀 Moving to position (29, 29)...")

    target_angles = {
        'base': 60,  # Calibrated: 45° → 60°
        'shoulder': 145,  # Calibrated: 140° → 145°
        'elbow': 160,  # Same as before
        'wrist_pitch': 90,  # Level wrist
        'wrist_roll': 90,  # Neutral roll
        'gripper': 0  # Closed for touching
    }

    # Move in correct directions with smooth transitions
    print("🔄 Moving base to 60°...")
    set_servo_smooth('base', target_angles['base'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving shoulder to 145°...")
    set_servo_smooth('shoulder', target_angles['shoulder'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving elbow to 160°...")
    set_servo_smooth('elbow', target_angles['elbow'], steps=8, delay=0.2)
    time.sleep(0.5)

    # Set wrist and gripper
    set_servo('wrist_pitch', target_angles['wrist_pitch'])
    set_servo('wrist_roll', target_angles['wrist_roll'])
    set_servo('gripper', target_angles['gripper'])

    print("✅ Target position (29,29) reached!")
    print("📏 Calibrated position: X=29cm, Y=29cm from base")


def move_to_position_22_22():
    """Automatically move arm to touch position (22, 22) - CALIBRATED"""
    print("🚀 Moving to position (22, 22)...")

    # CALIBRATED ANGLES FROM YOUR MANUAL TESTING:
    target_angles = {
        'base': 60,  # Same base as (29,29)
        'shoulder': 85,  # Calibrated: from 145° down to 85°
        'elbow': 160,  # Same elbow as (29,29)
        'wrist_pitch': 155,  # Calibrated: from 90° up to 155°
        'wrist_roll': 90,  # Neutral roll
        'gripper': 0  # Closed for touching
    }

    # Move in correct directions with smooth transitions
    print("🔄 Moving base to 60°...")
    set_servo_smooth('base', target_angles['base'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving shoulder to 85°...")
    set_servo_smooth('shoulder', target_angles['shoulder'], steps=12, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving elbow to 160°...")
    set_servo_smooth('elbow', target_angles['elbow'], steps=8, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving wrist pitch to 155°...")
    set_servo_smooth('wrist_pitch', target_angles['wrist_pitch'], steps=10, delay=0.2)
    time.sleep(0.5)

    # Set wrist roll and gripper
    set_servo('wrist_roll', target_angles['wrist_roll'])
    set_servo('gripper', target_angles['gripper'])

    print("✅ Target position (22,22) reached!")
    print("📏 Calibrated position: X=22cm, Y=22cm from base")


def move_to_position_23_21():
    """Automatically move arm to touch position (23, 21) - CALIBRATED"""
    print("🚀 Moving to position (23, 21)...")

    # CALIBRATED ANGLES FROM YOUR MANUAL TESTING:
    target_angles = {
        'base': 65,  # Calibrated: 55° → 65°
        'shoulder': 90,  # Calibrated: 95° → 90°
        'elbow': 160,  # Same elbow
        'wrist_pitch': 155,  # Calibrated: 140° → 155°
        'wrist_roll': 90,  # Neutral roll
        'gripper': 0  # Closed for touching
    }

    # Move in correct directions with smooth transitions
    print("🔄 Moving base to 65°...")
    set_servo_smooth('base', target_angles['base'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving shoulder to 90°...")
    set_servo_smooth('shoulder', target_angles['shoulder'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving elbow to 160°...")
    set_servo_smooth('elbow', target_angles['elbow'], steps=8, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving wrist pitch to 155°...")
    set_servo_smooth('wrist_pitch', target_angles['wrist_pitch'], steps=10, delay=0.2)
    time.sleep(0.5)

    # Set wrist roll and gripper
    set_servo('wrist_roll', target_angles['wrist_roll'])
    set_servo('gripper', target_angles['gripper'])

    print("✅ Target position (23,21) reached!")
    print("📏 Calibrated position: X=23cm, Y=21cm from base")


def move_to_position_15_30():
    """Automatically move arm to touch position (15, 30) - CALIBRATED"""
    print("🚀 Moving to position (15, 30)...")

    # CALIBRATED ANGLES FROM YOUR MANUAL TESTING:
    target_angles = {
        'base': 35,  # Calibrated: 30° → 35°
        'shoulder': 95,  # Calibrated: 120° → 95°
        'elbow': 155,  # Same elbow as estimated
        'wrist_pitch': 150,  # Calibrated: 100° → 150°
        'wrist_roll': 90,  # Neutral roll
        'gripper': 0  # Closed for touching
    }

    # Move in correct directions with smooth transitions
    print("🔄 Moving base to 35°...")
    set_servo_smooth('base', target_angles['base'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving shoulder to 95°...")
    set_servo_smooth('shoulder', target_angles['shoulder'], steps=10, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving elbow to 155°...")
    set_servo_smooth('elbow', target_angles['elbow'], steps=8, delay=0.2)
    time.sleep(0.5)

    print("🔄 Moving wrist pitch to 150°...")
    set_servo_smooth('wrist_pitch', target_angles['wrist_pitch'], steps=10, delay=0.2)
    time.sleep(0.5)

    # Set wrist roll and gripper
    set_servo('wrist_roll', target_angles['wrist_roll'])
    set_servo('gripper', target_angles['gripper'])

    print("✅ Target position (15,30) reached!")
    print("📏 Calibrated position: X=15cm, Y=30cm from base")


def run_position_sequence():
    """Run through all calibrated positions one by one"""
    print("\n" + "=" * 50)
    print("🎯 STARTING POSITION SEQUENCE")
    print("=" * 50)

    positions = [
        ("(29,29)", move_to_position_29_29),
        ("(22,22)", move_to_position_22_22),
        ("(23,21)", move_to_position_23_21),
        ("(15,30)", move_to_position_15_30)
    ]

    for position_name, position_function in positions:
        print(f"\n{'=' * 20} {position_name} {'=' * 20}")
        position_function()
        print(f"⏳ Pausing at {position_name} for 3 seconds...")
        time.sleep(3)

    print("\n" + "=" * 50)
    print("✅ POSITION SEQUENCE COMPLETE!")
    print("=" * 50)


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
    elif cmd == 'A':  # Changed from L to A for left
        move_servo('base', 5)
        return f"BASE:{servos['base']['angle']}°"
    elif cmd == 'S':  # Changed from R to S for right
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
    elif cmd == 'I':  # I = Wrist up
        move_servo('wrist_pitch', 5)
        return f"WPI:{servos['wrist_pitch']['angle']}°"
    elif cmd == 'K':  # K = Wrist down
        move_servo('wrist_pitch', -5)
        return f"WPI:{servos['wrist_pitch']['angle']}°"

    # Wrist Roll
    elif cmd == 'J':  # J = Wrist roll left
        move_servo('wrist_roll', 5)
        return f"WRO:{servos['wrist_roll']['angle']}°"
    elif cmd == 'L':  # L = Wrist roll right
        move_servo('wrist_roll', -5)
        return f"WRO:{servos['wrist_roll']['angle']}°"

    # Gripper
    elif cmd == 'C':
        set_servo('gripper', 90)  # Open
        return "GRIPPER:CLOSED:90°"
    elif cmd == 'O':
        set_servo('gripper', 0)  # Close
        return "GRIPPER:OPEN:0°"

    # Auto move to (29,29)
    elif cmd == 'G':  # G for "Go to position (29,29)"
        move_to_position_29_29()
        return "AUTO:POSITION_29_29_COMPLETE"

    # Auto move to (22,22)
    elif cmd == 'H':  # H for "Go to position (22,22)"
        move_to_position_22_22()
        return "AUTO:POSITION_22_22_COMPLETE"

    # Auto move to (23,21)
    elif cmd == 'J':  # J for "Go to position (23,21)"
        move_to_position_23_21()
        return "AUTO:POSITION_23_21_COMPLETE"

    # Auto move to (15,30)
    elif cmd == 'K':  # K for "Go to position (15,30)"
        move_to_position_15_30()
        return "AUTO:POSITION_15_30_COMPLETE"

    # Run complete sequence
    elif cmd == 'R':  # R for "Run sequence"
        run_position_sequence()
        return "SEQUENCE:ALL_POSITIONS_COMPLETE"

    # Emergency stop
    elif cmd == 'X':  # Changed from S to X for emergency stop
        set_servo('base', 90)
        set_servo('shoulder', 95)  # Return to custom safe position
        set_servo('elbow', 170)  # Return to custom safe position
        set_servo('wrist_pitch', 90)
        set_servo('wrist_roll', 90)
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
    # Start in custom safe position
    set_servo('base', 90)
    set_servo('shoulder', 95)  # Custom shoulder position
    set_servo('elbow', 170)  # Custom elbow position
    set_servo('wrist_pitch', 90)
    set_servo('wrist_roll', 180)
    set_servo('gripper', 0)  # Gripper closed
    time.sleep(0.5)
    print("✅ Arm ready!")

    # Don't auto-move on startup - let user choose
    print("💡 Ready! Press R to run position sequence")


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
G = Auto Go to (29,29) Position
H = Auto Go to (22,22) Position
J = Auto Go to (23,21) Position
K = Auto Go to (15,30) Position
R = Run Complete Position Sequence
X = Emergency Stop | ? = Get Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Calibrated Positions:
   (29,29): Base=60°, Shoulder=145°, Elbow=160°, Wrist=90°
   (22,22): Base=60°, Shoulder=85°, Elbow=160°, Wrist=155°
   (23,21): Base=65°, Shoulder=90°, Elbow=160°, Wrist=155°
   (15,30): Base=35°, Shoulder=95°, Elbow=155°, Wrist=150°
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Note: Press R to run through all positions automatically!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

# Setup non-blocking serial input
poll_obj = select.poll()
poll_obj.register(sys.stdin, select.POLLIN)

# Main loop
while True:
    if poll_obj.poll(10):  # 10ms timeout
        try:
            cmd = sys.stdin.readline().strip()
            if cmd:
                response = handle_command(cmd)
                print(f"💡 {response}")
        except Exception as e:
            print(f"❌ Error: {e}")
    time.sleep(0.01)