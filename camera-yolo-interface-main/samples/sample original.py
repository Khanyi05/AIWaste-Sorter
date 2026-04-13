# app.py - Fixed FastAPI Application (Corrected Gripper & Emergency Stop)
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


# Initialize Pico serial connection with proper settings
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
        # Wait for Pico to initialize
        time.sleep(2)
        # Clear buffers
        pico_serial.reset_input_buffer()
        pico_serial.reset_output_buffer()

        # Test communication
        pico_serial.write(b'HELLO\n')
        pico_serial.flush()
        time.sleep(1)

        # Read any initial response
        if pico_serial.in_waiting > 0:
            response = pico_serial.readline().decode().strip()
            print(f"Pico initial response: {response}")

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
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# Waste classes
waste_classes = {
    39: "Bottle",  # Plastic bottle
    40: "Wine glass",  # Glass
    43: "Cup",  # Paper/plastic cup
    44: "Fork",  # Utensils
    67: "Cell phone"  # E-waste
}

# Pico command mapping - CORRECTED GRIPPER & EMERGENCY STOP
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
    "GRIP_OPEN": "C",  # ✅ CORRECTED: C = Open (matches main.py)
    "GRIP_CLOSE": "O",  # ✅ CORRECTED: O = Close (matches main.py)
    "EMERGENCY_STOP": "X",  # ✅ CORRECTED: X = Emergency Stop (matches main.py)
}

# System state
detection_history = deque(maxlen=20)
history_lock = threading.Lock()
system_logs = deque(maxlen=50)
logs_lock = threading.Lock()
arm_status = "idle"
arm_lock = threading.Lock()


# Improved Pico communication function
def send_pico_command(cmd_char, delay=0.5):
    """Send command to Pico with robust response handling"""
    if not pico_serial or not pico_serial.is_open:
        print("⚠️ Pico not connected")
        return "NO_PICO_CONNECTION"

    try:
        # Clear input buffer
        pico_serial.reset_input_buffer()

        # Send command with newline
        full_cmd = cmd_char + '\n'
        print(f"📤 SENDING: '{cmd_char}'")

        pico_serial.write(full_cmd.encode('utf-8'))
        pico_serial.flush()  # Ensure data is sent

        # Wait for response
        response = ""
        start_time = time.time()
        while time.time() - start_time < 5:  # 5 second timeout
            if pico_serial.in_waiting > 0:
                line = pico_serial.readline().decode('utf-8').strip()
                if line:
                    response = line
                    print(f"📥 RECEIVED: '{response}'")
                    break
            time.sleep(0.1)

        # Wait for movement to complete
        time.sleep(delay)

        return response if response else "NO_RESPONSE"

    except Exception as e:
        error_msg = f"COMM_ERROR:{str(e)}"
        print(f"❌ {error_msg}")
        return error_msg


def send_cmd(cmd_key, delay=0.5):
    """Send mapped command to Pico"""
    cmd_char = pico_commands.get(cmd_key, "")
    if not cmd_char:
        print(f"❌ Invalid command key: {cmd_key}")
        return "INVALID_COMMAND"

    return send_pico_command(cmd_char, delay)


# Pixel to servo mapping
def map_pixel_to_servo(x, y, frame_width=640, frame_height=480):
    base_angle = np.interp(x, [0, frame_width], [180, 0])
    base_angle = int(max(45, min(135, base_angle)))

    shoulder_angle = np.interp(y, [150, 400], [70, 120])
    shoulder_angle = int(max(70, min(120, shoulder_angle)))

    elbow_angle = np.interp(y, [150, 400], [130, 170])
    elbow_angle = int(max(130, min(170, elbow_angle)))

    return base_angle, shoulder_angle, elbow_angle


def generate_frames():
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

                    detected_objects.append({
                        "material": label,
                        "confidence": conf_level,
                        "box": [x1, y1, x2, y2]
                    })

        # Update system state
        if detected_objects:
            current_time = datetime.now().isoformat()
            with history_lock:
                for obj in detected_objects:
                    detection_history.appendleft({
                        "material": obj["material"],
                        "timestamp": current_time,
                        "confidence": obj["confidence"]
                    })

            with logs_lock:
                for obj in detected_objects:
                    system_logs.appendleft({
                        "material": obj["material"],
                        "timestamp": current_time,
                        "confidence": obj["confidence"],
                        "id": str(len(system_logs) + 1)
                    })

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
            "temperature": "Normal",
            "sensors": True,
            "model": "YOLOv8n",
            "fps": 30
        }


@app.get("/api/classification")
async def get_classification():
    with history_lock:
        return detection_history[0] if detection_history else {
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


# HTML Interface with CORRECTED button labels
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Waste Sorter</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { height: 100vh; overflow: hidden; padding: 1rem; background-color: #f8f9fa; }
    .camera-container { background-color: #000; position: relative; overflow: hidden; display: flex; justify-content: center; align-items: center; }
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
  </style>
</head>
<body>
  <div class="container-fluid p-3" style="height: 100vh; overflow: hidden;">
    <div class="d-flex justify-content-between align-items-center mb-3 border-bottom pb-2">
      <h3>AI Waste Sorter</h3>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-success" data-bs-toggle="modal" data-bs-target="#logEntryModal">Add Log</button>
        <button class="btn btn-outline-danger" id="logoutBtn">Logout</button>
      </div>
    </div>

    <div class="row gx-3 gy-3" style="height: calc(100% - 70px)">
      <!-- Left Column -->
      <div class="col-lg-7 d-flex flex-column gap-3" style="height: 100%">
        <div class="card mb-3">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span class="fw-bold">📷 Camera Feed</span>
            <div class="badge bg-success">Online</div>
          </div>
          <div class="size-controls">
            <label>Size:</label>
            <input type="range" class="form-range size-slider" id="cameraSize" min="500" max="1200" value="800">
            <span id="sizeValue">800px</span>
          </div>
          <div class="card-body p-0 camera-container" id="cameraContainer">
            <img src="/video_feed" class="camera-feed" alt="Live Camera Feed" id="cameraFeed">
          </div>
        </div>

        <div class="card flex-grow-1">
          <div class="card-header fw-bold">Robot Arm Controller <span id="armStatus">(Idle)</span></div>
          <div class="card-body">
            <div class="row g-3">
              <!-- Base & Shoulder Controls -->
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

                <!-- Elbow Controls -->
                <div class="control-section">
                  <h6>Elbow</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-info flex-fill" id="moveElbowUp">Elbow ↑</button>
                    <button class="btn btn-info flex-fill" id="moveElbowDown">Elbow ↓</button>
                  </div>
                </div>
              </div>

              <!-- Wrist & Gripper Controls -->
              <div class="col-md-6">
                <!-- Wrist Pitch -->
                <div class="control-section">
                  <h6>Wrist Pitch</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-warning flex-fill" id="moveWristPitchUp">Pitch ↑</button>
                    <button class="btn btn-warning flex-fill" id="moveWristPitchDown">Pitch ↓</button>
                  </div>
                </div>

                <!-- Wrist Roll -->
                <div class="control-section">
                  <h6>Wrist Roll</h6>
                  <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-success flex-fill" id="moveWristRollLeft">Roll ←</button>
                    <button class="btn btn-success flex-fill" id="moveWristRollRight">Roll →</button>
                  </div>
                </div>

                <!-- Gripper Controls -->
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
          </div>
        </div>
      </div>

      <!-- Right Column -->
      <div class="col-lg-5 d-flex flex-column justify-content-between" style="height: 100%">
        <div class="card mb-3 classification-card">
          <div class="card-header fw-bold">AI Classification Result</div>
          <div class="card-body" id="classificationResult">
            <div class="text-center py-4">
              <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
              <p class="mt-2">Waiting for detection...</p>
            </div>
          </div>
        </div>

        <div class="card mb-3 flex-grow-1">
          <div class="card-header fw-bold">Detection Logs</div>
          <div class="card-body logs-container" id="logs">
            <div class="mb-3"><input type="text" id="logSearch" placeholder="Search by material..." class="form-control"></div>
            <table class="table table-sm table-hover table-bordered align-middle text-center">
              <thead class="table-light sticky-top"><tr><th>Material</th><th>Confidence</th><th>Timestamp</th></tr></thead>
              <tbody><tr><td colspan="3" class="text-muted">Loading logs...</td></tr></tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-header fw-bold">System Health</div>
          <div class="card-body" id="systemHealth">
            <div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div>
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
    document.addEventListener('DOMContentLoaded', function() {
      const cameraFeed = document.getElementById('cameraFeed');
      const cameraSizeSlider = document.getElementById('cameraSize');
      const sizeValue = document.getElementById('sizeValue');
      let currentSize = parseInt(cameraSizeSlider.value);
      updateCameraSize();
      cameraSizeSlider.addEventListener('input', function() { currentSize = this.value; sizeValue.textContent = currentSize + 'px'; updateCameraSize(); });
      function updateCameraSize() { cameraFeed.style.width = currentSize + 'px'; cameraFeed.style.height = 'auto'; }

      const API = { logs: '/api/logs', health: '/api/health', classification: '/api/classification', command: '/api/command' };
      const armStatusElement = document.getElementById('armStatus');
      const classificationResult = document.getElementById('classificationResult');
      const logsContainer = document.getElementById('logs');
      const systemHealth = document.getElementById('systemHealth');

      async function sendCommand(command) {
        try {
          const response = await fetch(API.command, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command }) });
          const result = await response.json();
          console.log('Command result:', result);
          updateArmStatus(command);
        } catch (error) { console.error('Command error:', error); }
      }

      function updateArmStatus(status) {
        const statusMap = { 
          'MOVE_SHOULDER_UP': 'Shoulder Up', 'MOVE_SHOULDER_DOWN': 'Shoulder Down', 
          'MOVE_BASE_LEFT': 'Base Left', 'MOVE_BASE_RIGHT': 'Base Right',
          'MOVE_ELBOW_UP': 'Elbow Up', 'MOVE_ELBOW_DOWN': 'Elbow Down',
          'MOVE_WRIST_PITCH_UP': 'Wrist Pitch Up', 'MOVE_WRIST_PITCH_DOWN': 'Wrist Pitch Down',
          'MOVE_WRIST_ROLL_LEFT': 'Wrist Roll Left', 'MOVE_WRIST_ROLL_RIGHT': 'Wrist Roll Right',
          'GRIP_OPEN': 'Opening Grip (C)', 'GRIP_CLOSE': 'Closing Grip (O)', 
          'EMERGENCY_STOP': '🛑 EMERGENCY STOPPED (X)' 
        };
        armStatusElement.textContent = `(${statusMap[status] || 'Idle'})`;
        armStatusElement.style.color = status === 'EMERGENCY_STOP' ? '#dc3545' : '#0d6efd';
      }

      // Event listeners for all controls - NOW CORRECTLY MAPPED
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

      // ✅ CORRECTED GRIPPER CONTROLS
      document.getElementById('gripOpen').addEventListener('click', () => sendCommand('GRIP_OPEN'));  // Sends 'C'
      document.getElementById('gripClose').addEventListener('click', () => sendCommand('GRIP_CLOSE')); // Sends 'O'
      document.getElementById('emergencyStop').addEventListener('click', () => sendCommand('EMERGENCY_STOP')); // Sends 'X'

      async function updateLogs() { 
        try { 
          const response = await fetch(API.logs); 
          const logs = await response.json(); 
          const tableBody = logsContainer.querySelector('tbody'); 
          tableBody.innerHTML = logs.map(log => `<tr><td>${log.material}</td><td><span class="badge ${log.confidence === 'High' ? 'bg-success' : log.confidence === 'Medium' ? 'bg-warning' : 'bg-danger'}">${log.confidence}</span></td><td style="font-size: 0.9rem">${new Date(log.timestamp).toLocaleString()}</td></tr>`).join(''); 
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
          classificationResult.innerHTML = `<div class="text-center"><h4 class="mb-3">Material: <span class="text-primary">${cls.material}</span></h4><p>Confidence: <strong>${cls.confidence}</strong></p><p>Last Detected: <em>${time}</em></p><button class="btn btn-outline-success mt-2" id="rescanBtn">🔁 Rescan</button></div>`; 
          document.getElementById('rescanBtn').addEventListener('click', updateClassification); 
        } catch (error) { 
          classificationResult.innerHTML = '<p class="text-danger">Error loading AI result</p>'; 
        } 
      }

      async function updateHealth() { 
        try { 
          const response = await fetch(API.health); 
          const h = await response.json(); 
          systemHealth.innerHTML = `
            <div class="d-flex justify-content-between mb-2"><span>Camera</span><span class="badge ${h.camera ? 'bg-success' : 'bg-danger'}">${h.camera ? 'Good' : 'Faulty'}</span></div>
            <div class="d-flex justify-content-between mb-2"><span>Arm Status</span><span class="badge ${h.arm === 'idle' ? 'bg-info' : 'bg-warning'}">${h.arm}</span></div>
            <div class="d-flex justify-content-between mb-2"><span>Pico Connected</span><span class="badge ${h.pico_connected ? 'bg-success' : 'bg-danger'}">${h.pico_connected ? 'Yes' : 'No'}</span></div>
            <div class="d-flex justify-content-between"><span>Model</span><span class="badge bg-primary">${h.model}</span></div>
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

      updateLogs(); 
      updateClassification(); 
      updateHealth();
      setInterval(updateLogs, 3000); 
      setInterval(updateClassification, 2000); 
      setInterval(updateHealth, 5000);
    });
  </script>
</body>
</html>
"""


if __name__ == '__main__':
    import uvicorn

    print("🚀 Starting AI Waste Sorter at http://localhost:8000")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        if pico_serial and pico_serial.is_open:
            pico_serial.close()