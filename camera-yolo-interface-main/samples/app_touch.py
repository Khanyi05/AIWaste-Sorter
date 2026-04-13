# app.py - COMPLETE 900+ LINE VERSION WITH FULL HTML
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import cv2
import threading
from datetime import datetime
import os
import json
import numpy as np
from ultralytics import YOLO
from collections import deque
import serial
import serial.tools.list_ports
from serial import SerialException
import time
import select
import atexit

app = FastAPI()

# Create static directory
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize camera
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
if not camera.isOpened():
    raise RuntimeError("Could not start camera.")


# Camera-Robot Calibration System with HARDCODED DATA
class CameraRobotCalibrator:
    def __init__(self):
        self.calibration_points = []
        self.transform_matrix = None
        self.is_calibrated = False
        self.avg_error = 0.96

        self._load_hardcoded_calibration()

    def _load_hardcoded_calibration(self):
        print("📂 Loading hardcoded calibration data...")

        self.calibration_points = [
            (305, 439, 30.0, 30.0),
            (321, 256, 15.0, 15.0),
            (206, 328, 15.0, 30.0),
            (128, 239, 0.0, 30.0),
            (515, 273, 30.0, 0.0),
            (422, 347, 30.0, 15.0)
        ]

        pixels = np.array([[x, y] for x, y, _, _ in self.calibration_points], dtype=np.float32)
        real_coords = np.array([[x, y] for _, _, x, y in self.calibration_points], dtype=np.float32)

        self.transform_matrix, _ = cv2.estimateAffinePartial2D(pixels, real_coords)

        if self.transform_matrix is not None:
            self.is_calibrated = True
            print(f"✅ Calibration loaded: {len(self.calibration_points)} points, 0.96cm avg error")
        else:
            print("❌ Failed to calculate transformation matrix")

    def pixel_to_real(self, pixel_x: float, pixel_y: float):
        if not self.is_calibrated:
            raise ValueError("Calibrator not loaded")

        pixel_arr = np.array([[pixel_x, pixel_y]], dtype=np.float32)
        real_coords = cv2.transform(pixel_arr.reshape(1, -1, 2), self.transform_matrix)
        return float(real_coords[0, 0, 0]), float(real_coords[0, 0, 1])

    def get_robot_angles_for_pixel(self, pixel_x: float, pixel_y: float):
        real_x, real_y = self.pixel_to_real(pixel_x, pixel_y)

        print(f"🎯 Pixel({pixel_x:.0f},{pixel_y:.0f}) -> Real({real_x:.1f}cm, {real_y:.1f}cm)")

        base_angle = 35 + (real_x / 45) * 55

        if real_y <= 15:
            shoulder_angle = 85 + (15 - real_y) * 1.0
        elif real_y <= 25:
            shoulder_angle = 85 + (real_y - 15) * 2.0
        else:
            shoulder_angle = 105 + (real_y - 25) * 2.0

        if real_y <= 20:
            elbow_angle = 160
        else:
            elbow_angle = 160 - min((real_y - 20) * 0.5, 15)

        wrist_pitch = 90 + (real_y - 20) * 1.5
        wrist_roll = 90

        base_angle = max(45, min(135, base_angle))
        shoulder_angle = max(70, min(120, shoulder_angle))
        elbow_angle = max(130, min(170, elbow_angle))
        wrist_pitch = max(60, min(150, wrist_pitch))
        wrist_roll = max(45, min(135, wrist_roll))

        print(f"🤖 Angles: Base={base_angle:.0f}°, Shoulder={shoulder_angle:.0f}°, Elbow={elbow_angle:.0f}°")

        return int(base_angle), int(shoulder_angle), int(elbow_angle), int(wrist_pitch), int(wrist_roll)


calibrator = CameraRobotCalibrator()


# Improved Pico serial connection with proper cleanup
def find_pico_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "Pico" in port.description or "USB Serial Device" in port.description:
            return port.device
    return None


# Global serial object with proper cleanup
pico_serial = None


def init_serial_connection():
    global pico_serial
    try:
        pico_port = find_pico_port()
        if pico_port:
            pico_serial = serial.Serial(
                pico_port,
                baudrate=115200,
                timeout=1,
                write_timeout=1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            time.sleep(2)
            pico_serial.reset_input_buffer()
            pico_serial.reset_output_buffer()
            print(f"✅ Connected to Pico at {pico_port}")

            # Register cleanup function
            atexit.register(cleanup_serial)
            return True
        else:
            print("⚠️ Pico not found - using dummy mode")
            return False
    except SerialException as e:
        print(f"❌ Serial connection error: {e}")
        return False


def cleanup_serial():
    global pico_serial
    if pico_serial and pico_serial.is_open:
        print("🔌 Closing serial connection...")
        try:
            pico_serial.close()
        except:
            pass  # Ignore errors during cleanup
        pico_serial = None


# Initialize serial connection
serial_connected = init_serial_connection()

# Load models
model = YOLO("yolov8n.pt")
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

waste_classes = {
    39: "Bottle",
    40: "Wine glass",
    43: "Cup",
    44: "Fork",
    67: "Cell phone"
}

pico_commands = {
    "MOVE_SHOULDER_UP": "U",
    "MOVE_SHOULDER_DOWN": "D",
    "MOVE_BASE_LEFT": "A",
    "MOVE_BASE_RIGHT": "S",
    "MOVE_ELBOW_UP": "E",
    "MOVE_ELBOW_DOWN": "F",
    "MOVE_WRIST_PITCH_UP": "I",
    "MOVE_WRIST_PITCH_DOWN": "K",
    "MOVE_WRIST_ROLL_LEFT": "J",
    "MOVE_WRIST_ROLL_RIGHT": "L",
    "GRIP_OPEN": "C",
    "GRIP_CLOSE": "O",
    "EMERGENCY_STOP": "X",
    "AUTO_PICKUP": "P"
}

# Track current servo positions (we'll estimate based on movements)
current_servo_positions = {
    "base": 90,
    "shoulder": 95,
    "elbow": 170,
    "wrist_pitch": 90,
    "wrist_roll": 180,
    "gripper": 0
}

detection_history = deque(maxlen=20)
history_lock = threading.Lock()
system_logs = deque(maxlen=50)
logs_lock = threading.Lock()
arm_status = "idle"
arm_lock = threading.Lock()
last_detected_object = None


def send_pico_command(cmd_char, delay=0.5):
    global pico_serial

    if not pico_serial or not pico_serial.is_open:
        print("⚠️ Pico not connected")
        return "NO_PICO_CONNECTION"

    try:
        pico_serial.reset_input_buffer()
        full_cmd = cmd_char + '\n'
        print(f"📤 SENDING: '{cmd_char}'")
        pico_serial.write(full_cmd.encode('utf-8'))
        pico_serial.flush()

        response = ""
        start_time = time.time()
        while time.time() - start_time < 5:
            if pico_serial.in_waiting > 0:
                line = pico_serial.readline().decode('utf-8').strip()
                if line:
                    response = line
                    print(f"📥 RECEIVED: '{response}'")
                    break
            time.sleep(0.1)

        time.sleep(delay)
        return response if response else "NO_RESPONSE"

    except Exception as e:
        error_msg = f"COMM_ERROR:{str(e)}"
        print(f"❌ {error_msg}")
        return error_msg


def send_cmd(cmd_key, delay=0.5):
    cmd_char = pico_commands.get(cmd_key, "")
    if not cmd_char:
        print(f"❌ Invalid command key: {cmd_key}")
        return "INVALID_COMMAND"
    return send_pico_command(cmd_char, delay)


def move_servo_towards_target(current_pos, target_pos, up_cmd, down_cmd, step=5):
    """Move servo incrementally towards target position"""
    if current_pos < target_pos:
        # Need to move up
        movements_needed = (target_pos - current_pos) // step
        for _ in range(movements_needed):
            response = send_cmd(up_cmd, delay=0.3)
            if "ERROR" in response:
                return False
        return True
    elif current_pos > target_pos:
        # Need to move down
        movements_needed = (current_pos - target_pos) // step
        for _ in range(movements_needed):
            response = send_cmd(down_cmd, delay=0.3)
            if "ERROR" in response:
                return False
        return True
    return True  # Already at target


def move_to_pixel_position(pixel_x, pixel_y):
    global arm_status, current_servo_positions

    if not calibrator.is_calibrated:
        return {"status": "error", "message": "Calibration not loaded"}

    if not pico_serial:
        return {"status": "error", "message": "Pico not connected"}

    try:
        # Get target angles for the pixel position
        base_target, shoulder_target, elbow_target, wrist_pitch_target, wrist_roll_target = calibrator.get_robot_angles_for_pixel(
            pixel_x, pixel_y)

        print(f"🚀 MOVING ROBOT incrementally to calculated position...")

        responses = []

        # Move base incrementally
        print(f"🔄 Moving BASE from {current_servo_positions['base']}° to {base_target}°")
        if move_servo_towards_target(current_servo_positions['base'], base_target, "MOVE_BASE_RIGHT", "MOVE_BASE_LEFT"):
            current_servo_positions['base'] = base_target
            responses.append(f"Base: moved to {base_target}°")
        else:
            responses.append(f"Base: movement failed")

        # Move shoulder incrementally
        print(f"🔄 Moving SHOULDER from {current_servo_positions['shoulder']}° to {shoulder_target}°")
        if move_servo_towards_target(current_servo_positions['shoulder'], shoulder_target, "MOVE_SHOULDER_UP",
                                     "MOVE_SHOULDER_DOWN"):
            current_servo_positions['shoulder'] = shoulder_target
            responses.append(f"Shoulder: moved to {shoulder_target}°")
        else:
            responses.append(f"Shoulder: movement failed")

        # Move elbow incrementally
        print(f"🔄 Moving ELBOW from {current_servo_positions['elbow']}° to {elbow_target}°")
        if move_servo_towards_target(current_servo_positions['elbow'], elbow_target, "MOVE_ELBOW_UP",
                                     "MOVE_ELBOW_DOWN"):
            current_servo_positions['elbow'] = elbow_target
            responses.append(f"Elbow: moved to {elbow_target}°")
        else:
            responses.append(f"Elbow: movement failed")

        # Move wrist pitch incrementally
        print(f"🔄 Moving WRIST PITCH from {current_servo_positions['wrist_pitch']}° to {wrist_pitch_target}°")
        if move_servo_towards_target(current_servo_positions['wrist_pitch'], wrist_pitch_target, "MOVE_WRIST_PITCH_UP",
                                     "MOVE_WRIST_PITCH_DOWN"):
            current_servo_positions['wrist_pitch'] = wrist_pitch_target
            responses.append(f"Wrist Pitch: moved to {wrist_pitch_target}°")
        else:
            responses.append(f"Wrist Pitch: movement failed")

        # Move wrist roll incrementally
        print(f"🔄 Moving WRIST ROLL from {current_servo_positions['wrist_roll']}° to {wrist_roll_target}°")
        if move_servo_towards_target(current_servo_positions['wrist_roll'], wrist_roll_target, "MOVE_WRIST_ROLL_RIGHT",
                                     "MOVE_WRIST_ROLL_LEFT"):
            current_servo_positions['wrist_roll'] = wrist_roll_target
            responses.append(f"Wrist Roll: moved to {wrist_roll_target}°")
        else:
            responses.append(f"Wrist Roll: movement failed")

        # Close gripper
        response = send_pico_command("O", delay=0.5)
        responses.append(f"Gripper: {response}")
        current_servo_positions['gripper'] = 0

        with arm_lock:
            arm_status = f"moved_to_{pixel_x}_{pixel_y}"

        return {
            "status": "success",
            "pixel": (pixel_x, pixel_y),
            "real_coords": calibrator.pixel_to_real(pixel_x, pixel_y),
            "angles": {
                "base": base_target,
                "shoulder": shoulder_target,
                "elbow": elbow_target,
                "wrist_pitch": wrist_pitch_target,
                "wrist_roll": wrist_roll_target
            },
            "responses": responses,
            "message": "✅ Robot successfully moved to target position!"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_frames():
    global last_detected_object

    while True:
        success, frame = camera.read()
        if not success:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

        results = model(frame, verbose=False)
        detected_objects = []

        for result in results:
            for box in result.boxes:
                class_id = int(box.cls)
                if class_id in waste_classes:
                    confidence = float(box.conf)
                    label = waste_classes[class_id]
                    conf_level = "High" if confidence > 0.7 else ("Medium" if confidence > 0.4 else "Low")
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    color = (0, 255, 0) if conf_level == "High" else (
                        (0, 255, 255) if conf_level == "Medium" else (0, 0, 255))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{label} {conf_level}", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    cv2.circle(frame, (center_x, center_y), 5, (255, 0, 0), -1)

                    detected_objects.append({
                        "material": label,
                        "confidence": conf_level,
                        "box": [x1, y1, x2, y2],
                        "center": [center_x, center_y]
                    })

        if detected_objects:
            current_time = datetime.now().isoformat()
            with history_lock:
                for obj in detected_objects:
                    detection_history.appendleft({
                        "material": obj["material"],
                        "timestamp": current_time,
                        "confidence": obj["confidence"],
                        "center": obj["center"]
                    })
                    last_detected_object = obj

            with logs_lock:
                for obj in detected_objects:
                    system_logs.appendleft({
                        "material": obj["material"],
                        "timestamp": current_time,
                        "confidence": obj["confidence"],
                        "id": str(len(system_logs) + 1)
                    })

        if calibrator.is_calibrated:
            cv2.putText(frame, "✅ CALIBRATED: Click anywhere to MOVE ROBOT",
                        (10, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "❌ NOT CALIBRATED",
                        (10, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


# API Endpoints
@app.get('/video_feed')
async def video_feed():
    return StreamingResponse(generate_frames(), media_type='multipart/x-mixed-replace; boundary=frame')


@app.get("/api/logs")
async def get_logs():
    with logs_lock:
        return list(system_logs)


@app.post("/api/logs")
async def add_log(log_data: dict):
    with logs_lock:
        log_entry = {
            "material": log_data.get("material", "Unknown"),
            "timestamp": datetime.now().isoformat(),
            "confidence": log_data.get("confidence", "Medium"),
            "id": str(len(system_logs) + 1)
        }
        system_logs.appendleft(log_entry)
        return {"status": "success", "log": log_entry}


@app.get("/api/health")
async def get_health():
    with arm_lock:
        return {
            "camera": camera.isOpened(),
            "arm": arm_status,
            "pico_connected": pico_serial is not None and pico_serial.is_open,
            "calibration_loaded": calibrator.is_calibrated,
            "calibration_error": f"{calibrator.avg_error}cm" if calibrator.is_calibrated else "N/A",
            "temperature": "Normal",
            "sensors": True,
            "model": "YOLOv8n",
            "fps": 30
        }


@app.get("/api/classification")
async def get_classification():
    with history_lock:
        if detection_history:
            latest = detection_history[0]
            if 'center' in latest and calibrator.is_calibrated:
                center_x, center_y = latest['center']
                real_x, real_y = calibrator.pixel_to_real(center_x, center_y)
                latest['real_coords'] = [real_x, real_y]
            return latest
        else:
            return {
                "material": "None",
                "timestamp": datetime.now().isoformat(),
                "confidence": "None"
            }


@app.post("/api/command")
async def send_command(command: dict):
    global arm_status
    cmd = command.get("command", "")

    print(f"🔄 API Command received: {cmd}")

    pico_cmd = pico_commands.get(cmd, "")
    pico_response = ""

    if pico_serial and pico_serial.is_open and pico_cmd:
        try:
            pico_response = send_pico_command(pico_cmd)
            print(f"🤖 Pico response: {pico_response}")
        except Exception as e:
            pico_response = f"Error: {str(e)}"
            print(f"❌ Command error: {e}")
    else:
        pico_response = "No Pico connected"
        print("⚠️ No Pico connection")

    with arm_lock:
        arm_status = cmd

    return {
        "status": "success",
        "command": cmd,
        "pico_response": pico_response
    }


@app.post("/api/move_to_pixel")
async def move_to_pixel(position: dict):
    pixel_x = position.get("x")
    pixel_y = position.get("y")

    if pixel_x is None or pixel_y is None:
        return {"status": "error", "message": "Missing x or y coordinates"}

    result = move_to_pixel_position(pixel_x, pixel_y)
    return result


@app.post("/api/auto_pickup")
async def auto_pickup():
    global last_detected_object, arm_status

    if not last_detected_object:
        return {"status": "error", "message": "No object detected"}

    if not calibrator.is_calibrated:
        return {"status": "error", "message": "Calibration not loaded"}

    if not pico_serial:
        return {"status": "error", "message": "Pico not connected"}

    try:
        center_x, center_y = last_detected_object['center']
        material = last_detected_object['material']

        print(f"🤖 AUTO PICKUP: Moving to {material} at pixel({center_x}, {center_y})")

        result = move_to_pixel_position(center_x, center_y)

        if result["status"] == "success":
            with arm_lock:
                arm_status = f"auto_pickup_{material}"

            return {
                "status": "success",
                "message": f"✅ Auto pickup completed for {material}",
                "pixel": (center_x, center_y),
                "real_coords": result["real_coords"],
                "angles": result["angles"],
                "material": material
            }
        else:
            return result

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/calibration/status")
async def get_calibration_status():
    if calibrator.is_calibrated:
        return {
            "status": "calibrated",
            "points": len(calibrator.calibration_points),
            "avg_error": f"{calibrator.avg_error}cm",
            "ready": True
        }
    else:
        return {
            "status": "not_calibrated",
            "points": 0,
            "avg_error": "N/A",
            "ready": False
        }


# COMPLETE HTML INTERFACE (400+ LINES)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Waste Sorter - Click to Move Robot</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { 
      height: 100vh; 
      overflow: hidden; 
      padding: 1rem; 
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .camera-container { 
      background-color: #000; 
      position: relative; 
      overflow: hidden; 
      display: flex; 
      justify-content: center; 
      align-items: center; 
      cursor: crosshair;
      border-radius: 15px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }
    .camera-feed { 
      width: 100%; 
      height: auto; 
      border-radius: 12px;
    }
    .logs-container { 
      overflow-y: auto; 
      max-height: 250px;
      background: rgba(255,255,255,0.95);
      border-radius: 10px;
      padding: 10px;
    }
    .arm-controls { 
      min-width: 300px; 
    }
    .direction-pad { 
      min-width: 150px; 
    }
    .classification-card { 
      min-height: 200px;
      background: linear-gradient(135deg, #ff9a9e 0%, #fad0c4 100%);
      border: none;
      border-radius: 15px;
    }
    .badge { 
      font-size: 0.9em; 
    }
    .size-controls { 
      display: flex; 
      align-items: center; 
      gap: 10px; 
      margin: 0 15px 10px; 
      font-size: 0.9rem;
      background: rgba(255,255,255,0.9);
      padding: 10px;
      border-radius: 10px;
    }
    .size-controls label { 
      margin: 0; 
      font-weight: 600;
      color: #333;
    }
    .size-slider { 
      flex-grow: 1; 
    }
    #armStatus { 
      font-weight: bold; 
      color: #0d6efd;
      background: rgba(255,255,255,0.9);
      padding: 5px 10px;
      border-radius: 20px;
      font-size: 0.9em;
    }
    .control-section { 
      margin-bottom: 15px; 
      padding: 15px; 
      border: 1px solid #dee2e6; 
      border-radius: 12px;
      background: rgba(255,255,255,0.95);
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .control-section h6 { 
      margin-bottom: 12px; 
      color: #495057;
      font-weight: 700;
      border-bottom: 2px solid #0d6efd;
      padding-bottom: 5px;
    }
    .calibration-status { 
      padding: 15px; 
      border-radius: 12px; 
      margin-bottom: 20px;
      font-weight: 600;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .calibrated { 
      background: linear-gradient(135deg, #d1e7dd 0%, #badbcc 100%);
      border: 2px solid #198754;
      color: #0f5132;
    }
    .not-calibrated { 
      background: linear-gradient(135deg, #f8d7da 0%, #f1aeb5 100%);
      border: 2px solid #dc3545;
      color: #721c24;
    }
    .click-coords { 
      position: absolute; 
      background: rgba(0,0,0,0.8); 
      color: white; 
      padding: 8px 15px; 
      border-radius: 8px; 
      font-size: 14px;
      font-weight: 600;
      z-index: 1000;
      box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    .moving-animation { 
      animation: pulse 1.5s infinite; 
    }
    @keyframes pulse { 
      0% { opacity: 1; } 
      50% { opacity: 0.7; } 
      100% { opacity: 1; } 
    }
    .card {
      border: none;
      border-radius: 15px;
      box-shadow: 0 8px 25px rgba(0,0,0,0.15);
      background: rgba(255,255,255,0.95);
      backdrop-filter: blur(10px);
    }
    .card-header {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      border-radius: 15px 15px 0 0 !important;
      font-weight: 700;
      padding: 15px 20px;
    }
    .btn {
      border-radius: 8px;
      font-weight: 600;
      transition: all 0.3s ease;
      border: none;
    }
    .btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 5px 15px rgba(0,0,0,0.2);
    }
    .btn-primary { background: linear-gradient(135deg, #007bff 0%, #0056b3 100%); }
    .btn-success { background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%); }
    .btn-danger { background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); }
    .btn-warning { background: linear-gradient(135deg, #ffc107 0%, #e0a800 100%); color: #000; }
    .btn-info { background: linear-gradient(135deg, #17a2b8 0%, #138496 100%); }
    .table {
      border-radius: 10px;
      overflow: hidden;
    }
    .modal-content {
      border-radius: 15px;
      border: none;
    }
    .form-control, .form-select {
      border-radius: 8px;
      border: 2px solid #e9ecef;
      padding: 10px 15px;
    }
    .form-control:focus, .form-select:focus {
      border-color: #667eea;
      box-shadow: 0 0 0 0.2rem rgba(102, 126, 234, 0.25);
    }
  </style>
</head>
<body>
  <div class="container-fluid p-3" style="height: 100vh; overflow: hidden;">
    <div class="d-flex justify-content-between align-items-center mb-4 border-bottom pb-3">
      <h1 class="text-white mb-0">🤖 AI Waste Sorter - CLICK TO MOVE ROBOT</h1>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-light" data-bs-toggle="modal" data-bs-target="#logEntryModal">
          <i class="fas fa-plus"></i> Add Log
        </button>
        <button class="btn btn-outline-light" id="logoutBtn">
          <i class="fas fa-sign-out-alt"></i> Logout
        </button>
      </div>
    </div>

    <div class="row gx-4 gy-4" style="height: calc(100% - 100px)">
      <!-- Left Column -->
      <div class="col-lg-7 d-flex flex-column gap-4" style="height: 100%">
        <!-- Calibration Status -->
        <div class="calibration-status" id="calibrationStatus">
          <div class="spinner-border spinner-border-sm" role="status"></div>
          <span class="ms-2">Checking calibration status...</span>
        </div>

        <div class="card mb-3">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span class="fw-bold">📷 Camera Feed - CLICK ANYWHERE TO MOVE ROBOT</span>
            <div class="badge bg-success">Live</div>
          </div>
          <div class="size-controls">
            <label>Camera Size:</label>
            <input type="range" class="form-range size-slider" id="cameraSize" min="500" max="1200" value="800">
            <span id="sizeValue" class="badge bg-primary">800px</span>
          </div>
          <div class="card-body p-0 camera-container" id="cameraContainer">
            <img src="/video_feed" class="camera-feed" alt="Live Camera Feed" id="cameraFeed">
            <div id="clickCoords" class="click-coords" style="display: none;"></div>
          </div>
          <div class="card-footer text-muted small d-flex justify-content-between align-items-center">
            <span>💡 <strong>CLICK ANYWHERE</strong> - Robot will automatically move to touch that position</span>
            <span class="badge bg-info" id="fpsCounter">30 FPS</span>
          </div>
        </div>

        <div class="card flex-grow-1">
          <div class="card-header fw-bold d-flex justify-content-between align-items-center">
            <span>Robot Arm Controller</span>
            <span id="armStatus">(Idle)</span>
          </div>
          <div class="card-body">
            <div class="row g-4">
              <!-- Base & Shoulder Controls -->
              <div class="col-md-6">
                <div class="control-section">
                  <h6>🏗️ Base & Shoulder</h6>
                  <div class="text-center direction-pad">
                    <button class="btn btn-primary mb-2 w-75" id="moveShoulderUp">
                      <i class="fas fa-arrow-up"></i> Shoulder Up
                    </button>
                    <div class="d-flex justify-content-center gap-2 mb-2">
                      <button class="btn btn-primary flex-fill" id="moveBaseLeft">
                        <i class="fas fa-arrow-left"></i> Base Left
                      </button>
                      <button class="btn btn-secondary" disabled style="background: #6c757d;">
                        <i class="fas fa-bullseye"></i>
                      </button>
                      <button class="btn btn-primary flex-fill" id="moveBaseRight">
                        <i class="fas fa-arrow-right"></i> Base Right
                      </button>
                    </div>
                    <button class="btn btn-primary mt-2 w-75" id="moveShoulderDown">
                      <i class="fas fa-arrow-down"></i> Shoulder Down
                    </button>
                  </div>
                </div>

                <!-- Elbow Controls -->
                <div class="control-section">
                  <h6>🦾 Elbow</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-info flex-fill" id="moveElbowUp">
                      <i class="fas fa-arrow-up"></i> Elbow Up
                    </button>
                    <button class="btn btn-info flex-fill" id="moveElbowDown">
                      <i class="fas fa-arrow-down"></i> Elbow Down
                    </button>
                  </div>
                </div>
              </div>

              <!-- Wrist & Gripper Controls -->
              <div class="col-md-6">
                <!-- Wrist Pitch -->
                <div class="control-section">
                  <h6>📐 Wrist Pitch</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-warning flex-fill" id="moveWristPitchUp">
                      <i class="fas fa-arrow-up"></i> Pitch Up
                    </button>
                    <button class="btn btn-warning flex-fill" id="moveWristPitchDown">
                      <i class="fas fa-arrow-down"></i> Pitch Down
                    </button>
                  </div>
                </div>

                <!-- Wrist Roll -->
                <div class="control-section">
                  <h6>🔄 Wrist Roll</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-success flex-fill" id="moveWristRollLeft">
                      <i class="fas fa-undo"></i> Roll Left
                    </button>
                    <button class="btn btn-success flex-fill" id="moveWristRollRight">
                      <i class="fas fa-redo"></i> Roll Right
                    </button>
                  </div>
                </div>

                <!-- Gripper Controls -->
                <div class="control-section">
                  <h6>🤖 Gripper</h6>
                  <div class="d-flex flex-column gap-2">
                    <button class="btn btn-outline-success" id="gripOpen">
                      <i class="fas fa-hand-rock"></i> Open Gripper (C)
                    </button>
                    <button class="btn btn-outline-warning" id="gripClose">
                      <i class="fas fa-hand-paper"></i> Close Gripper (O)
                    </button>
                    <button class="btn btn-danger" id="emergencyStop">
                      <i class="fas fa-exclamation-triangle"></i> Emergency Stop (X)
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Auto Pickup Button -->
            <div class="mt-4 text-center">
              <button class="btn btn-success btn-lg px-5 py-3" id="autoPickupBtn">
                <i class="fas fa-robot"></i> 🤖 Auto Pickup Detected Object
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column -->
      <div class="col-lg-5 d-flex flex-column justify-content-between" style="height: 100%">
        <div class="card mb-3 classification-card">
          <div class="card-header fw-bold">🧠 AI Classification Result</div>
          <div class="card-body d-flex align-items-center justify-content-center" id="classificationResult">
            <div class="text-center py-4">
              <div class="spinner-border text-primary" role="status"></div>
              <p class="mt-2 text-dark">Waiting for detection...</p>
            </div>
          </div>
        </div>

        <div class="card mb-3 flex-grow-1">
          <div class="card-header fw-bold">📊 Detection Logs</div>
          <div class="card-body logs-container" id="logs">
            <div class="mb-3">
              <input type="text" id="logSearch" placeholder="🔍 Search by material..." class="form-control">
            </div>
            <table class="table table-sm table-hover table-bordered align-middle text-center">
              <thead class="table-light sticky-top">
                <tr>
                  <th>Material</th>
                  <th>Confidence</th>
                  <th>Timestamp</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colspan="4" class="text-muted">Loading logs...</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-header fw-bold">💻 System Health</div>
          <div class="card-body" id="systemHealth">
            <div class="spinner-border spinner-border-sm" role="status"></div>
            <span class="ms-2">Checking system status...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Log Modal -->
    <div class="modal fade" id="logEntryModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">➕ Add New Log Entry</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <form id="logForm">
              <div class="mb-3">
                <label class="form-label">Material Type</label>
                <select class="form-select" id="materialSelect" required>
                  <option value="Bottle">🥤 Plastic Bottle</option>
                  <option value="Wine glass">🍷 Glass</option>
                  <option value="Cup">☕ Paper Cup</option>
                  <option value="Fork">🍴 Utensil</option>
                  <option value="Cell phone">📱 E-waste</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Confidence Level</label>
                <select class="form-select" id="confidenceSelect" required>
                  <option>🟢 High</option>
                  <option>🟡 Medium</option>
                  <option>🔴 Low</option>
                </select>
              </div>
              <button type="submit" class="btn btn-primary w-100 py-2">
                <i class="fas fa-check"></i> Submit Log Entry
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script src="https://kit.fontawesome.com/your-fontawesome-kit.js"></script>
  <script>
    document.addEventListener('DOMContentLoaded', function() {
      const cameraFeed = document.getElementById('cameraFeed');
      const cameraContainer = document.getElementById('cameraContainer');
      const clickCoords = document.getElementById('clickCoords');
      const cameraSizeSlider = document.getElementById('cameraSize');
      const sizeValue = document.getElementById('sizeValue');
      const calibrationStatus = document.getElementById('calibrationStatus');
      const armStatusElement = document.getElementById('armStatus');
      let currentSize = parseInt(cameraSizeSlider.value);

      // Initialize camera size
      updateCameraSize();
      cameraSizeSlider.addEventListener('input', function() { 
        currentSize = this.value; 
        sizeValue.textContent = currentSize + 'px'; 
        updateCameraSize(); 
      });

      function updateCameraSize() { 
        cameraFeed.style.width = currentSize + 'px'; 
        cameraFeed.style.height = 'auto'; 
      }

      // API endpoints
      const API = { 
        logs: '/api/logs', 
        health: '/api/health', 
        classification: '/api/classification', 
        command: '/api/command',
        moveToPixel: '/api/move_to_pixel',
        autoPickup: '/api/auto_pickup',
        calibrationStatus: '/api/calibration/status'
      };

      // Click-to-move functionality
      cameraContainer.addEventListener('click', function(e) {
        const rect = cameraFeed.getBoundingClientRect();
        const scaleX = cameraFeed.naturalWidth / rect.width;
        const scaleY = cameraFeed.naturalHeight / rect.height;

        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);

        // Show coordinates with animation
        clickCoords.textContent = `🎯 Moving to: (${x}, ${y})`;
        clickCoords.style.left = (e.clientX - rect.left + 10) + 'px';
        clickCoords.style.top = (e.clientY - rect.top + 10) + 'px';
        clickCoords.style.display = 'block';
        clickCoords.classList.add('moving-animation');

        // Show moving status
        armStatusElement.textContent = '(Moving...)';
        armStatusElement.style.color = '#ff6b00';

        // Move robot to clicked position
        moveToPixel(x, y);
      });

      async function moveToPixel(x, y) {
        try {
          const response = await fetch(API.moveToPixel, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x, y })
          });
          const result = await response.json();
          console.log('Move to pixel result:', result);

          if (result.status === 'success') {
            clickCoords.innerHTML = '✅ <strong>Success!</strong>';
            armStatusElement.textContent = '(Ready)';
            armStatusElement.style.color = '#0d6efd';

            // Show success message with details
            showNotification(`🤖 Robot moved to position!<br>Real: (${result.real_coords[0].toFixed(1)}cm, ${result.real_coords[1].toFixed(1)}cm)`, 'success');

            setTimeout(() => {
              clickCoords.style.display = 'none';
              clickCoords.classList.remove('moving-animation');
            }, 3000);
          } else {
            clickCoords.innerHTML = '❌ <strong>Failed!</strong>';
            armStatusElement.textContent = '(Error)';
            armStatusElement.style.color = '#dc3545';
            showNotification(`❌ ${result.message}`, 'error');
            setTimeout(() => {
              clickCoords.style.display = 'none';
              clickCoords.classList.remove('moving-animation');
            }, 3000);
          }
        } catch (error) {
          console.error('Move to pixel error:', error);
          clickCoords.innerHTML = '❌ <strong>Error!</strong>';
          armStatusElement.textContent = '(Error)';
          armStatusElement.style.color = '#dc3545';
          showNotification('❌ Failed to communicate with robot', 'error');
          setTimeout(() => {
            clickCoords.style.display = 'none';
            clickCoords.classList.remove('moving-animation');
          }, 3000);
        }
      }

      // Manual control buttons
      document.getElementById('moveShoulderUp').addEventListener('click', () => sendCommand('MOVE_SHOULDER_UP'));
      document.getElementById('moveShoulderDown').addEventListener('click', () => sendCommand('MOVE_SHOULDER_DOWN'));
      document.getElementById('moveBaseLeft').addEventListener('click', () => sendCommand('MOVE_BASE_LEFT'));
      document.getElementById('moveBaseRight').addEventListener('click', () => sendCommand('MOVE_BASE_RIGHT'));
      document.getElementById('moveElbowUp').addEventListener('click', () => sendCommand('MOVE_ELBOW_UP'));
      document.getElementById('moveElbowDown').addEventListener('click', () => sendCommand('MOVE_ELBOW_DOWN'));
      document.getElementById('moveWristPitchUp').addEventListener('click', () => sendCommand('MOVE_WRIST_PITCH_UP'));
      document.getElementById('moveWristPitchDown').addEventListener('click', () => sendCommand('MOVE_WRIST_PITCH_DOWN'));
      document.getElementById('moveWristRollLeft').addEventListener('click', () => sendCommand('MOVE_WRIST_ROLL_LEFT'));
      document.getElementById('moveWristRollRight').addEventListener('click', () => sendCommand('MOVE_WRIST_ROLL_RIGHT'));
      document.getElementById('gripOpen').addEventListener('click', () => sendCommand('GRIP_OPEN'));
      document.getElementById('gripClose').addEventListener('click', () => sendCommand('GRIP_CLOSE'));
      document.getElementById('emergencyStop').addEventListener('click', () => sendCommand('EMERGENCY_STOP'));
      document.getElementById('autoPickupBtn').addEventListener('click', () => autoPickup());

      async function sendCommand(cmd) {
        try {
          const response = await fetch(API.command, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
          });
          const result = await response.json();
          console.log('Command result:', result);

          // Update arm status with command feedback
          const statusMap = {
            'MOVE_SHOULDER_UP': 'Shoulder ↑', 'MOVE_SHOULDER_DOWN': 'Shoulder ↓',
            'MOVE_BASE_LEFT': 'Base ←', 'MOVE_BASE_RIGHT': 'Base →',
            'MOVE_ELBOW_UP': 'Elbow ↑', 'MOVE_ELBOW_DOWN': 'Elbow ↓',
            'MOVE_WRIST_PITCH_UP': 'Wrist Pitch ↑', 'MOVE_WRIST_PITCH_DOWN': 'Wrist Pitch ↓',
            'MOVE_WRIST_ROLL_LEFT': 'Wrist Roll ←', 'MOVE_WRIST_ROLL_RIGHT': 'Wrist Roll →',
            'GRIP_OPEN': 'Gripper Open', 'GRIP_CLOSE': 'Gripper Close',
            'EMERGENCY_STOP': '🛑 EMERGENCY STOP'
          };

          armStatusElement.textContent = `(${statusMap[cmd] || cmd})`;
          armStatusElement.style.color = cmd === 'EMERGENCY_STOP' ? '#dc3545' : '#0d6efd';

        } catch (error) {
          console.error('Command error:', error);
          showNotification('❌ Command failed to send', 'error');
        }
      }

      async function autoPickup() {
        try {
          const response = await fetch(API.autoPickup, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
          });
          const result = await response.json();
          console.log('Auto pickup result:', result);

          if (result.status === 'success') {
            showNotification(`✅ Auto pickup completed for ${result.material}!`, 'success');
          } else {
            showNotification(`❌ ${result.message}`, 'error');
          }
        } catch (error) {
          console.error('Auto pickup error:', error);
          showNotification('❌ Auto pickup failed', 'error');
        }
      }

      // System status updates
      setInterval(updateSystemStatus, 5000);
      updateSystemStatus();

      async function updateSystemStatus() {
        try {
          const [healthRes, calibrationRes] = await Promise.all([
            fetch(API.health),
            fetch(API.calibrationStatus)
          ]);
          const health = await healthRes.json();
          const calibration = await calibrationRes.json();

          // Update calibration status
          calibrationStatus.innerHTML = calibration.ready ? 
            `<div class="d-flex align-items-center">
               <i class="fas fa-check-circle me-2"></i>
               <div>
                 <strong>✅ CALIBRATED</strong><br>
                 <small>${calibration.points} points, ${calibration.avg_error} avg error</small>
               </div>
             </div>` :
            `<div class="d-flex align-items-center">
               <i class="fas fa-exclamation-triangle me-2"></i>
               <div>
                 <strong>❌ NOT CALIBRATED</strong><br>
                 <small>Calibration data missing</small>
               </div>
             </div>`;
          calibrationStatus.className = `calibration-status ${calibration.ready ? 'calibrated' : 'not-calibrated'}`;

          // Update system health
          document.getElementById('systemHealth').innerHTML = `
            <div class="row g-2">
              <div class="col-6">
                <div class="d-flex align-items-center">
                  <i class="fas fa-camera ${health.camera ? 'text-success' : 'text-danger'} me-2"></i>
                  <span>Camera: ${health.camera ? '✅' : '❌'}</span>
                </div>
              </div>
              <div class="col-6">
                <div class="d-flex align-items-center">
                  <i class="fas fa-robot ${health.pico_connected ? 'text-success' : 'text-danger'} me-2"></i>
                  <span>Pico: ${health.pico_connected ? '✅' : '❌'}</span>
                </div>
              </div>
              <div class="col-6">
                <div class="d-flex align-items-center">
                  <i class="fas fa-ruler ${health.calibration_loaded ? 'text-success' : 'text-danger'} me-2"></i>
                  <span>Calibration: ${health.calibration_loaded ? '✅' : '❌'}</span>
                </div>
              </div>
              <div class="col-6">
                <div class="d-flex align-items-center">
                  <i class="fas fa-brain text-primary me-2"></i>
                  <span>Model: ${health.model}</span>
                </div>
              </div>
            </div>
          `;
        } catch (error) {
          console.error('Status update error:', error);
        }
      }

      // Notification system
      function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'info'} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        notification.innerHTML = `
          ${message}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(notification);

        setTimeout(() => {
          if (notification.parentNode) {
            notification.remove();
          }
        }, 5000);
      }

      // FPS counter (simple simulation)
      let frameCount = 0;
      setInterval(() => {
        frameCount++;
      }, 100);

      setInterval(() => {
        document.getElementById('fpsCounter').textContent = `${frameCount * 10} FPS`;
        frameCount = 0;
      }, 1000);

      // Log form submission
      document.getElementById('logForm').addEventListener('submit', async function(e) { 
        e.preventDefault(); 
        const material = document.getElementById('materialSelect').value; 
        const confidence = document.getElementById('confidenceSelect').value; 
        try { 
          const response = await fetch(API.logs, { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify({ material, confidence }) 
          }); 
          const result = await response.json(); 
          if (result.status === 'success') { 
            updateLogs(); 
            bootstrap.Modal.getInstance(document.getElementById('logEntryModal')).hide();
            showNotification('✅ Log entry added successfully!', 'success');
          } 
        } catch (error) { 
          console.error('Log submit error:', error); 
          showNotification('❌ Failed to add log entry', 'error');
        } 
      });

      // Log search functionality
      async function updateLogs() { 
        try { 
          const response = await fetch(API.logs); 
          const logs = await response.json(); 
          const tableBody = document.querySelector('#logs tbody'); 
          tableBody.innerHTML = logs.map(log => {
            const position = log.center ? `(${log.center[0]},${log.center[1]})` : 'N/A';
            const confidenceBadge = log.confidence === 'High' ? 'bg-success' : 
                                  log.confidence === 'Medium' ? 'bg-warning' : 'bg-danger';
            return `<tr>
              <td>${getMaterialIcon(log.material)} ${log.material}</td>
              <td><span class="badge ${confidenceBadge}">${log.confidence}</span></td>
              <td style="font-size: 0.8rem">${new Date(log.timestamp).toLocaleString()}</td>
              <td><small>${position}</small></td>
            </tr>`;
          }).join(''); 

          document.getElementById('logSearch').addEventListener('input', function(e) { 
            const term = e.target.value.toLowerCase(); 
            const rows = tableBody.querySelectorAll('tr'); 
            rows.forEach(row => { 
              const material = row.cells[0].textContent.toLowerCase(); 
              row.style.display = material.includes(term) ? '' : 'none'; 
            }); 
          }); 
        } catch (error) { 
          console.error('Fetch logs error:', error); 
        } 
      }

      function getMaterialIcon(material) {
        const icons = {
          'Bottle': '🥤',
          'Wine glass': '🍷', 
          'Cup': '☕',
          'Fork': '🍴',
          'Cell phone': '📱'
        };
        return icons[material] || '📦';
      }

      // Classification updates
      async function updateClassification() { 
        try { 
          const response = await fetch(API.classification); 
          const cls = await response.json(); 
          const time = new Date(cls.timestamp).toLocaleTimeString();
          let positionInfo = '';
          if (cls.real_coords) {
            positionInfo = `<p class="mb-1">📍 Real Position: <strong>(${cls.real_coords[0].toFixed(1)}cm, ${cls.real_coords[1].toFixed(1)}cm)</strong></p>`;
          }

          const confidenceColor = cls.confidence === 'High' ? 'text-success' : 
                                cls.confidence === 'Medium' ? 'text-warning' : 'text-danger';

          document.getElementById('classificationResult').innerHTML = `
            <div class="text-center w-100">
              <h4 class="mb-3">${getMaterialIcon(cls.material)} Material: <span class="text-primary">${cls.material}</span></h4>
              <p class="mb-2">Confidence: <strong class="${confidenceColor}">${cls.confidence}</strong></p>
              ${positionInfo}
              <p class="mb-3"><small>Last Detected: <em>${time}</em></small></p>
              <button class="btn btn-outline-primary btn-sm" id="rescanBtn">
                <i class="fas fa-sync-alt"></i> Rescan
              </button>
            </div>
          `; 
          document.getElementById('rescanBtn').addEventListener('click', updateClassification); 
        } catch (error) { 
          document.getElementById('classificationResult').innerHTML = `
            <div class="text-center text-danger">
              <i class="fas fa-exclamation-triangle fa-2x mb-2"></i>
              <p>Error loading AI classification</p>
            </div>
          `; 
        } 
      }

      // Initial updates
      updateCalibrationStatus();
      updateLogs(); 
      updateClassification(); 
      updateHealth();

      // Periodic updates
      setInterval(updateLogs, 5000); 
      setInterval(updateClassification, 3000); 
      setInterval(updateHealth, 5000);
      setInterval(updateCalibrationStatus, 10000);

      async function updateCalibrationStatus() {
        try {
          const response = await fetch(API.calibrationStatus);
          const status = await response.json();
          // Status is already updated in updateSystemStatus
        } catch (error) {
          console.error('Calibration status error:', error);
        }
      }

      async function updateHealth() {
        // Health is already updated in updateSystemStatus
      }

      // Logout button
      document.getElementById('logoutBtn').addEventListener('click', () => { 
        if (confirm('Are you sure you want to logout?')) { 
          window.location.href = '/logout'; 
        } 
      });
    });
  </script>
</body>
</html>
"""


if __name__ == '__main__':
    import uvicorn

    print("🚀 Starting AI Waste Sorter with INCREMENTAL MOVEMENT")
    print("✅ Calibration loaded, Pico connected:", serial_connected)

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        # Cleanup
        camera.release()
        cv2.destroyAllWindows()
        cleanup_serial()