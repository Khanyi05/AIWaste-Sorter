# main.py - 6-DOF Robotic Arm Controller (Auto-run)
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

# ===== FINAL PIN MAPPING =====
servo_pins = {
    "base": 16,  # GP16
    "shoulder": 17,  # GP17
    "elbow": 21,  # GP21
    "wrist_roll": 18,  # GP18
    "wrist_pitch": 22,  # GP22
    "gripper": 26  # GP26
}

# Initialize PWM for all servos
servos = {}
for name, pin in servo_pins.items():
    pwm = PWM(Pin(pin))
    pwm.freq(SERVO_FREQ)
    servos[name] = {"pwm": pwm, "angle": 90}  # Start at neutral

# ===== RECORDED MOVEMENTS =====
# First sequence for 'Q'
recorded_movements_q = [
    # First sequence: Base right (6 moves)
    ("s",), ("s",), ("s",), ("s",), ("s",), ("s",),
    # Shoulder up (9 moves)
    ("u",), ("u",), ("u",), ("u",), ("u",), ("u",), ("u",), ("u",), ("u",),
    # Close gripper
    ("c",),
    # Shoulder up more (3 moves)
    ("u",), ("u",), ("u",),
    # Open gripper
    ("o",),
    # Shoulder down (3 moves)
    ("d",), ("d",), ("d",),
    # Base right more (13 moves)
    ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",),
    # Shoulder up again (3 moves)
    ("u",), ("u",), ("u",),
    # Close gripper again
    ("c",),
    # Shoulder down (7 moves)
    ("d",), ("d",), ("d",), ("d",), ("d",), ("d",), ("d",),
    # Base left (7 moves)
    ("a",), ("a",), ("a",), ("a",), ("a",), ("a",), ("a",)
]

# Second sequence for 'R' (based on your recent movements)
recorded_movements_r = [
    # Base left and elbow up sequence
    ("a",), ("a",),  # Base left 2x
    ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",),  # Elbow up 8x
    ("c",),  # Close gripper
    ("e",), ("e",),  # Elbow up 2x more
    ("u",), ("u",), ("u",),  # Shoulder up 5x
    ("c",), ("c",),  # Close gripper 2x (redundant but recorded)
    ("o",),  # Open gripper
    ("d",), ("d",), ("d",), ("d",),  # Shoulder down 5x
    ("a",), ("a",), ("a",), ("a",), ("a",), ("a",),  # Base left 6x
    ("u",), ("u",), ("u",), ("u",), ("u",),  # Shoulder up 5x
    ("c",),  # Close gripper
    ("d",), ("d",), ("d",), ("d",), ("d",), ("d",),  # Shoulder down 6x
]

# Third sequence for 'P' (based on your latest movements)
recorded_movements_p = [
    # Base right sequence
    ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",),  # 11x base right
    # Shoulder up sequence
    ("u",), ("u",), ("u",), ("u",), ("u",),  # 5x shoulder up
    # Elbow up sequence
    ("e",), ("e",), ("e",),  # 3x elbow up
    # Close gripper
    ("c",),
    # Shoulder up more
    ("u",), ("u",), ("u",),  # 3x shoulder up
    # Open gripper
    ("o",),
    # Shoulder down
    ("d",), ("d",), ("d",), ("d",), ("d",),  # 5x shoulder down
    # Base right more
    ("s",), ("s",), ("s",), ("s",), ("s",), ("s",), ("s",),  # 7x base right
    # Shoulder down more
    ("d",), ("d",), ("d",), ("d",), ("d",), ("d",),  # 6x shoulder down
    # Elbow up more
    ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",), ("e",),  # 10x elbow up
    # Close gripper
    ("c",),
    # Shoulder down final
    ("d",), ("d",), ("d",), ("d",), ("d",), ("d",),  # 6x shoulder down
]


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


def move_to_default_position():
    """Move arm to default resting position"""
    print("🏠 Moving to default position...")
    set_servo('base', 90)
    set_servo('shoulder', 95)
    set_servo('elbow', 85)
    set_servo('wrist_pitch', 65)
    set_servo('wrist_roll', 180)
    set_servo('gripper', 0)
    time.sleep(1)
    print("✅ Arm in default position!")


def play_recorded_movements(movements_list, sequence_name):
    """Play back recorded movements"""
    print(f"🎬 Playing {sequence_name} movements...")

    # Reset to starting position first
    print("🔄 Resetting to starting position...")
    move_to_default_position()

    for i, (cmd,) in enumerate(movements_list):
        print(f"▶️ Step {i + 1}/{len(movements_list)}: '{cmd}'")
        response = handle_command(cmd)
        print(f"💡 {response}")
        time.sleep(0.5)  # Increased delay for smoother movement

    print(f"✅ Finished playing {sequence_name} movements!")
    # Move to default position after completion
    move_to_default_position()


# ===== COMMAND HANDLER =====
def handle_command(cmd):
    cmd = cmd.strip().upper()

    if not cmd:
        return "ERROR:EMPTY_CMD"

    # Shoulder
    if cmd == 'U':
        move_servo('shoulder', 5)
        return f"SHOULDER:{servos['shoulder']['angle']}°"
    elif cmd == 'D':
        move_servo('shoulder', -5)
        return f"SHOULDER:{servos['shoulder']['angle']}°"

    # Base
    elif cmd == 'A':  # A = Base left
        move_servo('base', 5)
        return f"BASE:{servos['base']['angle']}°"
    elif cmd == 'S':  # S = Base right
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

    # Gripper - FIXED to match your original movements
    elif cmd == 'O':  # O = Open gripper (to 0°)
        set_servo('gripper', 0)
        return "GRIPPER:OPEN:0°"
    elif cmd == 'C':  # C = Close gripper (to 90°)
        set_servo('gripper', 90)
        return "GRIPPER:CLOSED:90°"

    # Play first recorded movements (Q)
    elif cmd == 'Q':
        play_recorded_movements(recorded_movements_q, "first")
        return "PLAYBACK_Q:COMPLETE"

    # Play second recorded movements (R)
    elif cmd == 'R':
        play_recorded_movements(recorded_movements_r, "second")
        return "PLAYBACK_R:COMPLETE"

    # Play third recorded movements (P)
    elif cmd == 'P':
        play_recorded_movements(recorded_movements_p, "third")
        return "PLAYBACK_P:COMPLETE"

    # Move to default position
    elif cmd == 'H':  # H for Home position
        move_to_default_position()
        return "HOME_POSITION:SET"

    # Emergency stop
    elif cmd == 'X':
        set_servo('base', 90)
        set_servo('shoulder', 95)
        set_servo('elbow', 170)
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
    print(f"📌 Using pins: {servo_pins}")
    # Start in default position
    move_to_default_position()
    print("✅ Arm ready!")


# ===== MAIN LOOP =====
setup_arm()

print("""
🎮 6-DOF Robotic Arm Controller
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Controls:
U/D = Shoulder Up/Down
A/S = Base Left/Right
E/F = Elbow Up/Down  
I/K = Wrist Pitch Up/Down
J/L = Wrist Roll Left/Right
O = Open Gripper (0°)
C = Close Gripper (90°)
Q = Play First Recorded Sequence
R = Play Second Recorded Sequence
P = Play Third Recorded Sequence
H = Home/Default Position
X = Emergency Stop
? = Get Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
First Sequence (Q):
• 19 base right moves (s)
• 15 shoulder up moves (u) 
• 10 shoulder down moves (d)
• 7 base left moves (a)
• 2 gripper closes (c)
• 1 gripper open (o)

Second Sequence (R):
• 8 base left moves (a)
• 10 elbow up moves (e)
• 10 shoulder up moves (u)
• 11 shoulder down moves (d)
• 4 gripper closes (c)
• 1 gripper open (o)

Third Sequence (P):
• 18 base right moves (s)
• 14 shoulder up moves (u)
• 17 shoulder down moves (d)
• 13 elbow up moves (e)
• 2 gripper closes (c)
• 1 gripper open (o)
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
            if cmd:  # Only process non-empty commands
                response = handle_command(cmd)
                print(f"💡 {response}")
        except Exception as e:
            print(f"❌ Error: {e}")
    time.sleep(0.01)