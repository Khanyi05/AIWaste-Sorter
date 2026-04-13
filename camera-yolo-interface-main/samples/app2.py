# app.py - Fixed version using existing Pico commands
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

        # HARDCODED CALIBRATION DATA FROM YOUR SUCCESSFUL RUN
        self._load_hardcoded_calibration()

    def _load_hardcoded_calibration(self):
        """Load your successful calibration data directly"""
        print("📂 Loading hardcoded calibration data...")

        # Your calibration points: (pixel_x, pixel_y, real_x_cm, real_y_cm)
        self.calibration_points = [
            (305, 439, 30.0, 30.0),
            (321, 256, 15.0, 15.0),
            (206, 328, 15.0, 30.0),
            (128, 239, 0.0, 30.0),
            (515, 273, 30.0, 0.0),
            (422, 347, 30.0, 15.0)
        ]

        # Calculate transformation matrix from your points
        pixels = np.array([[x, y] for x, y, _, _ in self.calibration_points], dtype=np.float32)
        real_coords = np.array([[x, y] for _, _, x, y in self.calibration_points], dtype=np.float32)

        # Calculate transformation matrix
        self.transform_matrix, _ = cv2.estimateAffinePartial2D(pixels, real_coords)

        if self.transform_matrix is not None:
            self.is_calibrated = True
            print(f"✅ Calibration loaded: {len(self.calibration_points)} points, 0.96cm avg error")
            print(f"🔧 Transformation matrix calculated successfully")
        else:
            print("❌ Failed to calculate transformation matrix")

    def pixel_to_real(self, pixel_x: float, pixel_y: float):
        if not self.is_calibrated:
            raise ValueError("Calibrator not loaded")

        pixel_arr = np.array([[pixel_x, pixel_y]], dtype=np.float32)
        real_coords = cv2.transform(pixel_arr.reshape(1, -1, 2), self.transform_matrix)
        return float(real_coords[0, 0, 0]), float(real_coords[0, 0, 1])

    def get_robot_angles_for_pixel(self, pixel_x: float, pixel_y: float):
        """Convert pixel coordinates to robot angles using EXACT calibrated positions"""
        real_x, real_y = self.pixel_to_real(pixel_x, pixel_y)

        print(f"🎯 Pixel({pixel_x:.0f},{pixel_y:.0f}) -> Real({real_x:.1f}cm, {real_y:.1f}cm)")

        # EXACT MAPPING BASED ON YOUR CALIBRATED POSITIONS
        calibrated_positions = {
            (29, 29): (60, 145, 160, 90),  # Base, Shoulder, Elbow, Wrist
            (22, 22): (60, 85, 160, 155),
            (23, 21): (65, 90, 160, 155),
            (15, 30): (35, 95, 155, 150)
        }

        # Find the closest calibrated position
        closest_pos = None
        min_distance = float('inf')

        for cal_pos, angles in calibrated_positions.items():
            distance = ((real_x - cal_pos[0]) ** 2 + (real_y - cal_pos[1]) ** 2) ** 0.5
            if distance < min_distance:
                min_distance = distance
                closest_pos = cal_pos
                base_angle, shoulder_angle, elbow_angle, wrist_pitch = angles

        print(
            f"📍 Closest calibrated position: {closest_pos} -> Base={base_angle}°, Shoulder={shoulder_angle}°, Elbow={elbow_angle}°")

        # If we're close to a known position, use those exact angles
        if min_distance < 5:  # Within 5cm of a calibrated position
            wrist_roll = 90
            print(
                f"🎯 USING EXACT CALIBRATED ANGLES: Base={base_angle}°, Shoulder={shoulder_angle}°, Elbow={elbow_angle}°")
        else:
            # Fallback to interpolation for positions between calibrated points
            print("📍 Position between calibrated points, using interpolation")

            # Simple interpolation between your calibrated positions
            if real_x <= 22:
                base_angle = 35 + (real_x - 15) * (60 - 35) / (22 - 15)
            else:
                base_angle = 60 + (real_x - 22) * (65 - 60) / (23 - 22)

            if real_y <= 22:
                shoulder_angle = 95 + (real_y - 15) * (85 - 95) / (22 - 15)
            else:
                shoulder_angle = 85 + (real_y - 22) * (145 - 85) / (29 - 22)

            elbow_angle = 160  # Mostly constant in your data
            wrist_pitch = 150 if real_y <= 21 else 90
            wrist_roll = 90

        # Clamp to safe ranges
        base_angle = max(35, min(70, base_angle))
        shoulder_angle = max(85, min(145, shoulder_angle))
        elbow_angle = max(155, min(160, elbow_angle))
        wrist_pitch = max(90, min(155, wrist_pitch))
        wrist_roll = max(45, min(135, wrist_roll))

        print(
            f"🤖 Final Angles: Base={base_angle:.0f}°, Shoulder={shoulder_angle:.0f}°, Elbow={elbow_angle:.0f}°, WristP={wrist_pitch:.0f}°")

        return int(base_angle), int(shoulder_angle), int(elbow_angle), int(wrist_pitch), int(wrist_roll)
# Initialize calibrator - NO FILE NEEDED!
calibrator = CameraRobotCalibrator()


# Initialize Pico serial connection
def find_pico_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "Pico" in port.description or "USB Serial Device" in port.description:
            return port.device
    return None


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
    else:
        print("⚠️ Pico not found - using dummy mode")
        pico_serial = None
except SerialException as e:
    print(f"❌ Serial connection error: {e}")
    pico_serial = None

# Load models
model = YOLO("yolov8n.pt")
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Waste classes
waste_classes = {
    39: "Bottle",  # Plastic bottle
    40: "Wine glass",  # Glass
    43: "Cup",  # Paper/plastic cup
    44: "Fork",  # Utensils
    67: "Cell phone"  # E-waste
}

# Pico command mapping
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

# System state
detection_history = deque(maxlen=20)
history_lock = threading.Lock()
system_logs = deque(maxlen=50)
logs_lock = threading.Lock()
arm_status = "idle"
arm_lock = threading.Lock()
last_detected_object = None
current_angles = {"base": 60, "shoulder": 90, "elbow": 160, "wrist_pitch": 90,
                  "wrist_roll": 90}  # Default home position


# Improved Pico communication
def send_pico_command(cmd_char, delay=0.5):
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


def move_to_angles_smart(base_target, shoulder_target, elbow_target, wrist_pitch_target, wrist_roll_target):
    """Smart movement using existing manual commands"""
    global current_angles

    print(f"🎯 Moving to: Base={base_target}°, Shoulder={shoulder_target}°, Elbow={elbow_target}°")

    # Calculate differences from current position
    base_diff = base_target - current_angles["base"]
    shoulder_diff = shoulder_target - current_angles["shoulder"]
    elbow_diff = elbow_target - current_angles["elbow"]

    # Determine movement sequence
    movements = []

    # Base movement
    if abs(base_diff) > 5:  # Only move if significant difference
        if base_diff > 0:
            movements.extend(["MOVE_BASE_RIGHT"] * int(abs(base_diff) // 10))
        else:
            movements.extend(["MOVE_BASE_LEFT"] * int(abs(base_diff) // 10))

    # Shoulder movement
    if abs(shoulder_diff) > 5:
        if shoulder_diff > 0:
            movements.extend(["MOVE_SHOULDER_UP"] * int(abs(shoulder_diff) // 10))
        else:
            movements.extend(["MOVE_SHOULDER_DOWN"] * int(abs(shoulder_diff) // 10))

    # Elbow movement
    if abs(elbow_diff) > 5:
        if elbow_diff > 0:
            movements.extend(["MOVE_ELBOW_UP"] * int(abs(elbow_diff) // 10))
        else:
            movements.extend(["MOVE_ELBOW_DOWN"] * int(abs(elbow_diff) // 10))

    # Execute movements
    results = []
    for movement in movements:
        print(f"🔄 Executing: {movement}")
        result = send_cmd(movement, delay=0.3)  # Shorter delay for smoother movement
        results.append(result)
        time.sleep(0.2)  # Small pause between movements

    # Update current angles
    current_angles = {
        "base": base_target,
        "shoulder": shoulder_target,
        "elbow": elbow_target,
        "wrist_pitch": wrist_pitch_target,
        "wrist_roll": wrist_roll_target
    }

    return f"MOVEMENT_COMPLETED: {len(movements)} commands executed"


def move_to_pixel_position(pixel_x, pixel_y):
    """Move robot to a specific pixel position using smart movement"""
    global arm_status, current_angles

    if not calibrator.is_calibrated:
        return {"status": "error", "message": "Calibration not loaded"}

    try:
        # Get robot angles for the pixel position
        base_angle, shoulder_angle, elbow_angle, wrist_pitch, wrist_roll = calibrator.get_robot_angles_for_pixel(
            pixel_x, pixel_y)

        print(f"🤖 MOVING to: Base={base_angle}°, Shoulder={shoulder_angle}°, Elbow={elbow_angle}°")

        with arm_lock:
            arm_status = f"moving_to_{pixel_x}_{pixel_y}"

        # Use smart movement with existing commands
        movement_result = move_to_angles_smart(base_angle, shoulder_angle, elbow_angle, wrist_pitch, wrist_roll)

        real_x, real_y = calibrator.pixel_to_real(pixel_x, pixel_y)

        return {
            "status": "success",
            "pixel": (pixel_x, pixel_y),
            "real_coords": (real_x, real_y),
            "angles": {
                "base": base_angle,
                "shoulder": shoulder_angle,
                "elbow": elbow_angle,
                "wrist_pitch": wrist_pitch,
                "wrist_roll": wrist_roll
            },
            "movement_result": movement_result,
            "message": f"Arm moving to position! {movement_result}"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_frames():
    global last_detected_object

    while True:
        success, frame = camera.read()
        if not success:
            break

        # Face detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

        # Waste detection
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

                    # Calculate center of bounding box
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    cv2.circle(frame, (center_x, center_y), 5, (255, 0, 0), -1)

                    detected_objects.append({
                        "material": label,
                        "confidence": conf_level,
                        "box": [x1, y1, x2, y2],
                        "center": [center_x, center_y]
                    })

        # Update system state
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

        # Add calibration info overlay
        if calibrator.is_calibrated:
            cv2.putText(frame, "✅ CALIBRATED: Click anywhere to MOVE ARM to position",
                        (10, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "❌ NOT CALIBRATED",
                        (10, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # Add current arm status
        with arm_lock:
            status_text = f"ARM: {arm_status}"
            cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Encode and yield frame
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
            "pico_connected": pico_serial is not None,
            "calibration_loaded": calibrator.is_calibrated,
            "calibration_error": f"{calibrator.avg_error}cm" if calibrator.is_calibrated else "N/A",
            "current_angles": current_angles,
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
            # Add pixel coordinates for the latest detection
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

    if pico_serial and pico_cmd:
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
    """Calculate robot position for a specific pixel coordinate AND MOVE THERE"""
    pixel_x = position.get("x")
    pixel_y = position.get("y")

    if pixel_x is None or pixel_y is None:
        return {"status": "error", "message": "Missing x or y coordinates"}

    result = move_to_pixel_position(pixel_x, pixel_y)
    return result


@app.post("/api/auto_pickup")
async def auto_pickup():
    """Complete auto pickup sequence"""
    global arm_status, last_detected_object

    if not last_detected_object:
        return {"status": "error", "message": "No object detected"}

    try:
        center_x, center_y = last_detected_object['center']
        material = last_detected_object['material']

        print(f"🤖 Starting auto pickup for {material} at ({center_x}, {center_y})")

        with arm_lock:
            arm_status = "auto_pickup_sequence"

        # Move to object
        move_result = move_to_pixel_position(center_x, center_y)
        if move_result["status"] != "success":
            return move_result

        time.sleep(1)

        # Pickup sequence
        send_cmd("GRIP_OPEN", delay=1.0)
        time.sleep(0.5)
        send_cmd("GRIP_CLOSE", delay=1.0)
        time.sleep(1)

        # Return home
        home_result = move_to_angles_smart(60, 90, 160, 90, 90)

        return {
            "status": "success",
            "message": f"Auto pickup completed for {material}",
            "pickup_position": (center_x, center_y),
            "movement_result": home_result
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/calibration/status")
async def get_calibration_status():
    """Get calibration status and info"""
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


# HTML Interface (same as before)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # [Keep the same HTML content from previous version]
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>AI Waste Sorter - Click to Move Arm!</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
      <style>
        body { height: 100vh; overflow: hidden; padding: 1rem; background-color: #f8f9fa; }
        .camera-container { background-color: #000; position: relative; overflow: hidden; display: flex; justify-content: center; align-items: center; cursor: crosshair; }
        .camera-feed { width: 100%; height: auto; border-radius: 8px; }
        .logs-container { overflow-y: auto; max-height: 250px; }
        .arm-controls { min-width: 300px; }
        .direction-pad { min-width: 150px; }
        .classification-card { min-height: 200px; }
        .badge { font-size: 0.9em; }
        .size-controls { display: flex; align-items: center; gap: 10px; margin: 0 15px 10px; font-size: 0.9rem; }
        .size-controls label { margin: 0; font-weight: 500; }
        .size-slider { flex-grow: 1; }
        #armStatus { font-weight: bold; color: #0d6efd; }
        .control-section { margin-bottom: 15px; padding: 10px; border: 1px solid #dee2e6; border-radius: 5px; }
        .control-section h6 { margin-bottom: 10px; color: #495057; }
        .calibration-status { padding: 10px; border-radius: 5px; margin-bottom: 15px; }
        .calibrated { background-color: #d1e7dd; border: 1px solid #badbcc; }
        .not-calibrated { background-color: #f8d7da; border: 1px solid #f1aeb5; }
        .click-coords { position: absolute; background: rgba(0,0,0,0.7); color: white; padding: 5px 10px; border-radius: 3px; font-size: 12px; }
        .moving { animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
      </style>
    </head>
    <body>
      <div class="container-fluid p-3" style="height: 100vh; overflow: hidden;">
        <div class="d-flex justify-content-between align-items-center mb-3 border-bottom pb-2">
          <h3>🤖 AI Waste Sorter - Click to Move Arm!</h3>
          <div class="d-flex gap-2">
            <button class="btn btn-outline-success" data-bs-toggle="modal" data-bs-target="#logEntryModal">Add Log</button>
            <button class="btn btn-outline-danger" id="logoutBtn">Logout</button>
          </div>
        </div>

        <div class="row gx-3 gy-3" style="height: calc(100% - 70px)">
          <!-- Left Column -->
          <div class="col-lg-7 d-flex flex-column gap-3" style="height: 100%">
            <!-- Calibration Status -->
            <div class="calibration-status" id="calibrationStatus">
              <div class="spinner-border spinner-border-sm" role="status"></div>
              <span class="ms-2">Checking calibration status...</span>
            </div>

            <div class="card mb-3">
              <div class="card-header d-flex justify-content-between align-items-center">
                <span class="fw-bold">📷 Camera Feed - CLICK TO MOVE ARM</span>
                <div class="badge bg-success">Online</div>
              </div>
              <div class="size-controls">
                <label>Size:</label>
                <input type="range" class="form-range size-slider" id="cameraSize" min="500" max="1200" value="800">
                <span id="sizeValue">800px</span>
              </div>
              <div class="card-body p-0 camera-container" id="cameraContainer">
                <img src="/video_feed" class="camera-feed" alt="Live Camera Feed" id="cameraFeed">
                <div id="clickCoords" class="click-coords" style="display: none;"></div>
              </div>
              <div class="card-footer text-muted small">
                💡 <strong>CLICK ANYWHERE</strong> on the camera feed to automatically move the arm to that position!
              </div>
            </div>

            <div class="card flex-grow-1">
              <div class="card-header fw-bold">Robot Arm Controller <span id="armStatus">(Idle)</span></div>
              <div class="card-body">
                <div class="row g-3">
                  <!-- Manual controls remain the same -->
                  <div class="col-md-6">
                    <div class="control-section">
                      <h6>Base & Shoulder</h6>
                      <div class="text-center direction-pad">
                        <button class="btn btn-primary mb-2 w-75" id="moveShoulderUp">Shoulder ↑</button>
                        <div class="d-flex justify-content-center gap-2 mb-2">
                          <button class="btn btn-primary flex-fill" id="moveBaseLeft">Base ←</button>
                          <button class="btn btn-secondary" disabled>○</button>
                          <button class="btn btn-primary flex-fill" id="moveBaseRight">Base →</button>
                        </div>
                        <button class="btn btn-primary mt-2 w-75" id="moveShoulderDown">Shoulder ↓</button>
                      </div>
                    </div>
                    <div class="control-section">
                      <h6>Elbow</h6>
                      <div class="d-flex justify-content-center gap-2">
                        <button class="btn btn-info flex-fill" id="moveElbowUp">Elbow ↑</button>
                        <button class="btn btn-info flex-fill" id="moveElbowDown">Elbow ↓</button>
                      </div>
                    </div>
                  </div>
                  <div class="col-md-6">
                    <div class="control-section">
                      <h6>Wrist Pitch</h6>
                      <div class="d-flex justify-content-center gap-2">
                        <button class="btn btn-warning flex-fill" id="moveWristPitchUp">Pitch ↑</button>
                        <button class="btn btn-warning flex-fill" id="moveWristPitchDown">Pitch ↓</button>
                      </div>
                    </div>
                    <div class="control-section">
                      <h6>Wrist Roll</h6>
                      <div class="d-flex justify-content-center gap-2">
                        <button class="btn btn-success flex-fill" id="moveWristRollLeft">Roll ←</button>
                        <button class="btn btn-success flex-fill" id="moveWristRollRight">Roll →</button>
                      </div>
                    </div>
                    <div class="control-section">
                      <h6>Gripper</h6>
                      <div class="d-flex flex-column gap-2">
                        <button class="btn btn-outline-success" id="gripOpen">👐 Open (C)</button>
                        <button class="btn btn-outline-warning" id="gripClose">✊ Close (O)</button>
                        <button class="btn btn-danger" id="emergencyStop">❌ Emergency Stop (X)</button>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Auto Pickup Button -->
                <div class="mt-3 text-center">
                  <button class="btn btn-success btn-lg" id="autoPickupBtn">
                    🤖 Full Auto Pickup Sequence
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Right Column -->
          <div class="col-lg-5 d-flex flex-column justify-content-between" style="height: 100%">
            <div class="card mb-3 classification-card">
              <div class="card-header fw-bold">AI Classification Result</div>
              <div class="card-body" id="classificationResult">
                <div class="text-center py-4">
                  <div class="spinner-border text-primary" role="status"></div>
                  <p class="mt-2">Waiting for detection...</p>
                </div>
              </div>
            </div>

            <div class="card mb-3 flex-grow-1">
              <div class="card-header fw-bold">Detection Logs</div>
              <div class="card-body logs-container" id="logs">
                <div class="mb-3"><input type="text" id="logSearch" placeholder="Search by material..." class="form-control"></div>
                <table class="table table-sm table-hover table-bordered align-middle text-center">
                  <thead class="table-light sticky-top"><tr><th>Material</th><th>Confidence</th><th>Timestamp</th><th>Position</th></tr></thead>
                  <tbody><tr><td colspan="4" class="text-muted">Loading logs...</td></tr></tbody>
                </table>
              </div>
            </div>

            <div class="card">
              <div class="card-header fw-bold">System Health</div>
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
              <div class="modal-header"><h5 class="modal-title">Add New Log Entry</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
              <div class="modal-body">
                <form id="logForm">
                  <div class="mb-3"><label class="form-label">Material Type</label>
                    <select class="form-select" id="materialSelect" required>
                      <option value="Bottle">Plastic Bottle</option><option value="Wine glass">Glass</option>
                      <option value="Cup">Paper Cup</option><option value="Fork">Utensil</option><option value="Cell phone">E-waste</option>
                    </select>
                  </div>
                  <div class="mb-3"><label class="form-label">Confidence</label>
                    <select class="form-select" id="confidenceSelect" required><option>High</option><option>Medium</option><option>Low</option></select>
                  </div>
                  <button type="submit" class="btn btn-primary w-100">Submit</button>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>

      <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
      <script>
        // [Keep the same JavaScript from previous version]
        document.addEventListener('DOMContentLoaded', function() {
          const cameraFeed = document.getElementById('cameraFeed');
          const cameraContainer = document.getElementById('cameraContainer');
          const clickCoords = document.getElementById('clickCoords');
          const cameraSizeSlider = document.getElementById('cameraSize');
          const sizeValue = document.getElementById('sizeValue');
          const calibrationStatus = document.getElementById('calibrationStatus');
          let currentSize = parseInt(cameraSizeSlider.value);

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

          const API = { 
            logs: '/api/logs', 
            health: '/api/health', 
            classification: '/api/classification', 
            command: '/api/command',
            moveToPixel: '/api/move_to_pixel',
            autoPickup: '/api/auto_pickup',
            calibrationStatus: '/api/calibration/status'
          };

          const armStatusElement = document.getElementById('armStatus');
          const classificationResult = document.getElementById('classificationResult');
          const logsContainer = document.getElementById('logs');
          const systemHealth = document.getElementById('systemHealth');

          // Click-to-move functionality
          cameraContainer.addEventListener('click', function(e) {
            const rect = cameraFeed.getBoundingClientRect();
            const scaleX = cameraFeed.naturalWidth / rect.width;
            const scaleY = cameraFeed.naturalHeight / rect.height;

            const x = Math.round((e.clientX - rect.left) * scaleX);
            const y = Math.round((e.clientY - rect.top) * scaleY);

            // Show coordinates
            clickCoords.textContent = `Moving to: (${x}, ${y})`;
            clickCoords.style.left = (e.clientX - rect.left + 10) + 'px';
            clickCoords.style.top = (e.clientY - rect.top + 10) + 'px';
            clickCoords.style.display = 'block';
            clickCoords.classList.add('moving');

            setTimeout(() => {
              clickCoords.style.display = 'none';
              clickCoords.classList.remove('moving');
            }, 3000);

            // AUTOMATICALLY MOVE THE ARM!
            moveToPixel(x, y);
          });

          async function moveToPixel(x, y) {
            try {
              // Show moving status
              armStatusElement.textContent = '(Moving...)';
              armStatusElement.style.color = '#ffc107';

              const response = await fetch(API.moveToPixel, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x, y })
              });
              const result = await response.json();
              console.log('Move to pixel result:', result);

              if (result.status === 'success') {
                updateArmStatus(`Moved to (${x},${y})`);

                // Show success message
                showNotification(`Arm moving to position! ${result.message}`, 'success');

                // Update system health to show new angles
                updateHealth();
              } else {
                showNotification('Movement failed: ' + result.message, 'error');
                updateArmStatus('Movement failed');
              }
            } catch (error) {
              console.error('Move to pixel error:', error);
              showNotification('Failed to move arm: ' + error.message, 'error');
              updateArmStatus('Movement error');
            }
          }

          function showNotification(message, type) {
            // Create notification element
            const notification = document.createElement('div');
            notification.className = `alert alert-${type === 'success' ? 'success' : 'danger'} alert-dismissible fade show`;
            notification.style.position = 'fixed';
            notification.style.top = '20px';
            notification.style.right = '20px';
            notification.style.zIndex = '9999';
            notification.style.minWidth = '300px';
            notification.innerHTML = `
              ${message}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            document.body.appendChild(notification);

            // Auto remove after 5 seconds
            setTimeout(() => {
              if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
              }
            }, 5000);
          }

          async function sendCommand(command) {
            try {
              const response = await fetch(API.command, { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ command }) 
              });
              const result = await response.json();
              console.log('Command result:', result);
              updateArmStatus(command);
            } catch (error) { 
              console.error('Command error:', error); 
            }
          }

          function updateArmStatus(status) {
            const statusMap = { 
              'MOVE_SHOULDER_UP': 'Shoulder Up', 'MOVE_SHOULDER_DOWN': 'Shoulder Down', 
              'MOVE_BASE_LEFT': 'Base Left', 'MOVE_BASE_RIGHT': 'Base Right',
              'MOVE_ELBOW_UP': 'Elbow Up', 'MOVE_ELBOW_DOWN': 'Elbow Down',
              'MOVE_WRIST_PITCH_UP': 'Wrist Pitch Up', 'MOVE_WRIST_PITCH_DOWN': 'Wrist Pitch Down',
              'MOVE_WRIST_ROLL_LEFT': 'Wrist Roll Left', 'MOVE_WRIST_ROLL_RIGHT': 'Wrist Roll Right',
              'GRIP_OPEN': 'Opening Grip', 'GRIP_CLOSE': 'Closing Grip', 
              'EMERGENCY_STOP': '🛑 EMERGENCY STOPPED',
              'AUTO_PICKUP': 'Auto Pickup'
            };
            armStatusElement.textContent = `(${statusMap[status] || status || 'Idle'})`;
            armStatusElement.style.color = status === 'EMERGENCY_STOP' ? '#dc3545' : 
                                         status.includes('Moving') ? '#ffc107' : '#0d6efd';
          }

          // Event listeners for all controls
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
          document.getElementById('autoPickupBtn').addEventListener('click', autoPickup);

          async function autoPickup() {
            try {
              const response = await fetch(API.autoPickup, { method: 'POST' });
              const result = await response.json();
              console.log('Auto pickup result:', result);

              if (result.status === 'success') {
                updateArmStatus('AUTO_PICKUP');
                showNotification(`Auto pickup completed for ${result.material}!`, 'success');
              } else {
                showNotification('Auto pickup failed: ' + result.message, 'error');
              }
            } catch (error) {
              console.error('Auto pickup error:', error);
              showNotification('Auto pickup failed: ' + error.message, 'error');
            }
          }

          async function updateCalibrationStatus() {
            try {
              const response = await fetch(API.calibrationStatus);
              const status = await response.json();

              if (status.status === 'calibrated') {
                calibrationStatus.innerHTML = `
                  <div class="calibrated">
                    <strong>✅ CALIBRATED</strong> - ${status.points} points, ${status.avg_error} avg error
                    <br><small><strong>CLICK ANYWHERE</strong> on camera feed to move arm automatically!</small>
                  </div>
                `;
              } else {
                calibrationStatus.innerHTML = `
                  <div class="not-calibrated">
                    <strong>❌ NOT CALIBRATED</strong> - Calibration data missing
                    <br><small>Camera-robot mapping not available</small>
                  </div>
                `;
              }
            } catch (error) {
              console.error('Calibration status error:', error);
            }
          }

          async function updateLogs() { 
            try { 
              const response = await fetch(API.logs); 
              const logs = await response.json(); 
              const tableBody = logsContainer.querySelector('tbody'); 
              tableBody.innerHTML = logs.map(log => {
                const position = log.center ? `(${log.center[0]},${log.center[1]})` : 'N/A';
                return `<tr>
                  <td>${log.material}</td>
                  <td><span class="badge ${log.confidence === 'High' ? 'bg-success' : log.confidence === 'Medium' ? 'bg-warning' : 'bg-danger'}">${log.confidence}</span></td>
                  <td style="font-size: 0.9rem">${new Date(log.timestamp).toLocaleString()}</td>
                  <td>${position}</td>
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
            } catch (error) { console.error('Fetch logs error:', error); } 
          }

          async function updateClassification() { 
            try { 
              const response = await fetch(API.classification); 
              const cls = await response.json(); 
              const time = new Date(cls.timestamp).toLocaleTimeString();
              let positionInfo = '';
              if (cls.real_coords) {
                positionInfo = `<p>Real Position: <strong>(${cls.real_coords[0].toFixed(1)}cm, ${cls.real_coords[1].toFixed(1)}cm)</strong></p>`;
              }
              classificationResult.innerHTML = `
                <div class="text-center">
                  <h4 class="mb-3">Material: <span class="text-primary">${cls.material}</span></h4>
                  <p>Confidence: <strong>${cls.confidence}</strong></p>
                  ${positionInfo}
                  <p>Last Detected: <em>${time}</em></p>
                  <button class="btn btn-outline-success mt-2" id="rescanBtn">🔁 Rescan</button>
                  <button class="btn btn-primary mt-2" id="moveToObjectBtn">🤖 Move to Object</button>
                </div>
              `; 
              document.getElementById('rescanBtn').addEventListener('click', updateClassification);
              document.getElementById('moveToObjectBtn').addEventListener('click', function() {
                if (cls.center) {
                  moveToPixel(cls.center[0], cls.center[1]);
                }
              });
            } catch (error) { 
              classificationResult.innerHTML = '<p class="text-danger">Error loading AI result</p>'; 
            } 
          }

          async function updateHealth() { 
            try { 
              const response = await fetch(API.health); 
              const h = await response.json(); 
              let anglesInfo = '';
              if (h.current_angles) {
                anglesInfo = `
                  <div class="mt-2 p-2 bg-light rounded">
                    <small><strong>Current Angles:</strong><br>
                    Base: ${h.current_angles.base}° | Shoulder: ${h.current_angles.shoulder}°<br>
                    Elbow: ${h.current_angles.elbow}° | Wrist: ${h.current_angles.wrist_pitch}°
                    </small>
                  </div>
                `;
              }
              systemHealth.innerHTML = `
                <div class="d-flex justify-content-between mb-2"><span>Camera</span><span class="badge ${h.camera ? 'bg-success' : 'bg-danger'}">${h.camera ? 'Good' : 'Faulty'}</span></div>
                <div class="d-flex justify-content-between mb-2"><span>Arm Status</span><span class="badge ${h.arm === 'idle' ? 'bg-info' : h.arm.includes('moving') ? 'bg-warning' : 'bg-primary'}">${h.arm}</span></div>
                <div class="d-flex justify-content-between mb-2"><span>Pico Connected</span><span class="badge ${h.pico_connected ? 'bg-success' : 'bg-danger'}">${h.pico_connected ? 'Yes' : 'No'}</span></div>
                <div class="d-flex justify-content-between mb-2"><span>Calibration</span><span class="badge ${h.calibration_loaded ? 'bg-success' : 'bg-danger'}">${h.calibration_loaded ? 'Loaded' : 'Missing'}</span></div>
                ${anglesInfo}
              `; 
            } catch (error) { 
              systemHealth.innerHTML = '<span class="text-danger">Health check failed</span>'; 
            } 
          }

          document.getElementById('logForm').addEventListener('submit', async function(e) { 
            e.preventDefault(); 
            const material = document.getElementById('materialSelect').value; 
            const confidence = document.getElementById('confidenceSelect').value; 
            try { 
              const response = await fetch(API.logs, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ material, confidence }) }); 
              const result = await response.json(); 
              if (result.status === 'success') { 
                updateLogs(); 
                bootstrap.Modal.getInstance(document.getElementById('logEntryModal')).hide(); 
              } 
            } catch (error) { console.error('Log submit error:', error); } 
          });

          document.getElementById('logoutBtn').addEventListener('click', () => { if (confirm('Logout?')) window.location.href = '/logout'; });

          // Initial updates
          updateCalibrationStatus();
          updateLogs(); 
          updateClassification(); 
          updateHealth();

          // Periodic updates
          setInterval(updateLogs, 3000); 
          setInterval(updateClassification, 2000); 
          setInterval(updateHealth, 5000);
          setInterval(updateCalibrationStatus, 10000);
        });
      </script>
    </body>
    </html>
    """


if __name__ == '__main__':
    import uvicorn

    print("🚀 Starting AI Waste Sorter with SMART AUTOMATIC MOVEMENT at http://localhost:8000")
    print("📊 Calibration Status:", "Loaded" if calibrator.is_calibrated else "Not Loaded")
    if calibrator.is_calibrated:
        print("🎯 Accuracy: 0.96cm average error")
        print("💡 FEATURE: Click anywhere on camera feed to automatically move the arm!")
        print("🤖 USING: Smart movement with existing Pico commands")
        print("📏 Calibration points:", len(calibrator.calibration_points))

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        if pico_serial and pico_serial.is_open:
            pico_serial.close()