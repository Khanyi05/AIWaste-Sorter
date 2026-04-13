# app.py - AI Waste Sorter with Pico Arm Control
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

app = FastAPI()

# Create static directory if it doesn't exist
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize camera with proper settings
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
if not camera.isOpened():
    raise RuntimeError("Could not start camera.")


# Initialize Pico serial connection
def find_pico_port():
    """Find the serial port connected to Raspberry Pi Pico"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "Pico" in port.description or "USB Serial Device" in port.description:
            return port.device
    return None


try:
    pico_port = find_pico_port()
    if pico_port:
        pico_serial = serial.Serial(pico_port, baudrate=115200, timeout=1)
        print(f"✅ Connected to Pico at {pico_port}")
    else:
        print("⚠️ Pico not found - using dummy mode")
        pico_serial = None
except SerialException as e:
    print(f"❌ Serial connection error: {e}")
    pico_serial = None

# Load YOLOv8 model and Haar cascades
model = YOLO("yolov8n.pt")  # Load official model (for demo)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# Waste classes we'll detect
waste_classes = {
    39: "Bottle",  # Plastic bottle
    40: "Wine glass",  # Glass
    43: "Cup",  # Paper/plastic cup
    44: "Fork",  # Utensils
    67: "Cell phone"  # E-waste
}

# System state (thread-safe)
detection_history = deque(maxlen=20)
history_lock = threading.Lock()
system_logs = deque(maxlen=50)
logs_lock = threading.Lock()
arm_status = "idle"
arm_lock = threading.Lock()


def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break

        # Face and eye detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
            roi_gray = gray[y:y + h, x:x + w]
            roi_color = frame[y:y + h, x:x + w]

            eyes = eye_cascade.detectMultiScale(roi_gray)
            for (ex, ey, ew, eh) in eyes:
                cv2.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), (0, 255, 0), 2)

        # Waste detection with YOLOv8
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

    # Command mapping for Pico
    pico_commands = {
        "MOVE_UP": "U",
        "MOVE_DOWN": "D",
        "MOVE_LEFT": "L",
        "MOVE_RIGHT": "R",
        "GRIP_OPEN": "O",
        "GRIP_CLOSE": "C",
        "EMERGENCY_STOP": "S"
    }

    pico_cmd = pico_commands.get(cmd, "")
    pico_response = ""

    if pico_serial and pico_cmd:
        try:
            pico_serial.write(f"{pico_cmd}\n".encode())
            pico_response = pico_serial.readline().decode().strip()
            print(f"🤖 Pico response: {pico_response}")
        except Exception as e:
            print(f"❌ Pico communication error: {e}")
            pico_response = f"Error: {str(e)}"

    with arm_lock:
        arm_status = cmd

    return {
        "status": "success",
        "command": cmd,
        "pico_response": pico_response if pico_cmd else "No Pico connected"
    }


# HTML Interface (keep your existing HTML response exactly as is)
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
    body {
      height: 100vh;
      overflow: hidden;
      padding: 1rem;
      background-color: #f8f9fa;
    }
    .main-content {
      height: calc(100% - 70px);
    }
    /* Camera container with dynamic size */
    .camera-container {
      background-color: #000;
      position: relative;
      overflow: hidden;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    .camera-feed {
      width: 100%;
      height: auto;
      border-radius: 8px;
    }
    .logs-container {
      overflow-y: auto;
      max-height: 250px;
    }
    .arm-controls {
      min-width: 300px;
    }
    .direction-pad {
      min-width: 150px;
    }
    .classification-card {
      min-height: 200px;
    }
    .badge { font-size: 0.9em; }

    /* Size control slider */
    .size-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 15px 10px;
      font-size: 0.9rem;
    }
    .size-controls label {
      margin: 0;
      font-weight: 500;
    }
    .size-slider {
      flex-grow: 1;
    }
    #armStatus {
      font-weight: bold;
      color: #0d6efd;
    }
  </style>
</head>
<body>
  <div class="container-fluid p-3" style="height: 100vh; overflow: hidden;">
    <!-- Header -->
    <div class="d-flex justify-content-between align-items-center mb-3 border-bottom pb-2">
      <h3>AI Waste Sorter</h3>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-success" data-bs-toggle="modal" data-bs-target="#logEntryModal">
          Add Log
        </button>
        <button class="btn btn-outline-danger" id="logoutBtn">Logout</button>
      </div>
    </div>

    <div class="row gx-3 gy-3" style="height: calc(100% - 70px)">
      <!-- Left Column: Camera + Arm -->
      <div class="col-lg-7 d-flex flex-column gap-3" style="height: 100%">
        <!-- Camera Feed with Resize -->
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
          <div class="card-header fw-bold">
            Robot Arm Controller <span id="armStatus">(Idle)</span>
          </div>
          <div class="card-body d-flex justify-content-center align-items-center">
            <div class="d-flex justify-content-between flex-wrap gap-4 arm-controls">
              <!-- Direction Controls -->
              <div class="text-center direction-pad">
                <button class="btn btn-primary mb-2" id="moveUp">↑</button>
                <div>
                  <button class="btn btn-primary me-2" id="moveLeft">←</button>
                  <button class="btn btn-secondary" disabled>○</button>
                  <button class="btn btn-primary ms-2" id="moveRight">→</button>
                </div>
                <button class="btn btn-primary mt-2" id="moveDown">↓</button>
              </div>

              <!-- Grip + Stop Controls -->
              <div class="d-flex flex-column gap-2 justify-content-center">
                <button class="btn btn-outline-success" id="gripOpen">👐 Open Grip</button>
                <button class="btn btn-outline-warning" id="gripClose">✊ Close Grip</button>
                <button class="btn btn-danger" id="emergencyStop">❌ Emergency Stop</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Classification + Logs + Health -->
      <div class="col-lg-5 d-flex flex-column justify-content-between" style="height: 100%">
        <div class="card mb-3 classification-card">
          <div class="card-header fw-bold">AI Classification Result</div>
          <div class="card-body" id="classificationResult">
            <div class="text-center py-4">
              <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
              <p class="mt-2">Waiting for detection...</p>
            </div>
          </div>
        </div>

        <div class="card mb-3 flex-grow-1">
          <div class="card-header fw-bold">Detection Logs</div>
          <div class="card-body logs-container" id="logs">
            <div class="mb-3">
              <input type="text" id="logSearch" placeholder="Search by material..." class="form-control">
            </div>
            <table class="table table-sm table-hover table-bordered align-middle text-center">
              <thead class="table-light sticky-top">
                <tr>
                  <th>Material</th>
                  <th>Confidence</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                <tr><td colspan="3" class="text-muted">Loading logs...</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-header fw-bold">System Health</div>
          <div class="card-body" id="systemHealth">
            <div class="spinner-border spinner-border-sm" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
            <span class="ms-2">Checking system status...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Log Modal -->
    <div class="modal fade" id="logEntryModal" tabindex="-1" aria-labelledby="logEntryModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="logEntryModalLabel">Add New Log Entry</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <form id="logForm">
              <div class="mb-3">
                <label class="form-label">Material Type</label>
                <select class="form-select" id="materialSelect" required>
                  <option value="Bottle">Plastic Bottle</option>
                  <option value="Wine glass">Glass</option>
                  <option value="Cup">Paper Cup</option>
                  <option value="Fork">Utensil</option>
                  <option value="Cell phone">E-waste</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Confidence</label>
                <select class="form-select" id="confidenceSelect" required>
                  <option>High</option>
                  <option>Medium</option>
                  <option>Low</option>
                </select>
              </div>
              <button type="submit" class="btn btn-primary w-100">Submit</button>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Bootstrap JS -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

  <!-- Custom JS -->
  <script>
    document.addEventListener('DOMContentLoaded', function() {
      const cameraFeed = document.getElementById('cameraFeed');
      const cameraSizeSlider = document.getElementById('cameraSize');
      const sizeValue = document.getElementById('sizeValue');

      // Set initial size
      let currentSize = parseInt(cameraSizeSlider.value);
      updateCameraSize();

      // Update size on slider input
      cameraSizeSlider.addEventListener('input', function() {
        currentSize = this.value;
        sizeValue.textContent = currentSize + 'px';
        updateCameraSize();
      });

      function updateCameraSize() {
        cameraFeed.style.width = currentSize + 'px';
        cameraFeed.style.height = 'auto';
      }

      // Make responsive
      window.addEventListener('resize', updateCameraSize);

      // === API ENDPOINTS ===
      const API = {
        logs: '/api/logs',
        health: '/api/health',
        classification: '/api/classification',
        command: '/api/command'
      };

      const armStatusElement = document.getElementById('armStatus');
      const classificationResult = document.getElementById('classificationResult');
      const logsContainer = document.getElementById('logs');
      const systemHealth = document.getElementById('systemHealth');

      // Send arm command
      async function sendCommand(command) {
        try {
          const response = await fetch(API.command, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command })
          });
          const result = await response.json();
          updateArmStatus(command);
        } catch (error) {
          console.error('Command error:', error);
        }
      }

      function updateArmStatus(status) {
        const statusMap = {
          'MOVE_UP': 'Moving Up',
          'MOVE_DOWN': 'Moving Down',
          'MOVE_LEFT': 'Moving Left',
          'MOVE_RIGHT': 'Moving Right',
          'GRIP_OPEN': 'Opening Grip',
          'GRIP_CLOSE': 'Closing Grip',
          'EMERGENCY_STOP': 'EMERGENCY STOPPED'
        };
        armStatusElement.textContent = `(${statusMap[status] || 'Idle'})`;
        armStatusElement.style.color = status === 'EMERGENCY_STOP' ? '#dc3545' : '#0d6efd';
      }

      // Arm control listeners
      document.getElementById('moveUp').addEventListener('click', () => sendCommand('MOVE_UP'));
      document.getElementById('moveDown').addEventListener('click', () => sendCommand('MOVE_DOWN'));
      document.getElementById('moveLeft').addEventListener('click', () => sendCommand('MOVE_LEFT'));
      document.getElementById('moveRight').addEventListener('click', () => sendCommand('MOVE_RIGHT'));
      document.getElementById('gripOpen').addEventListener('click', () => sendCommand('GRIP_OPEN'));
      document.getElementById('gripClose').addEventListener('click', () => sendCommand('GRIP_CLOSE'));
      document.getElementById('emergencyStop').addEventListener('click', () => sendCommand('EMERGENCY_STOP'));

      // Update logs
      async function updateLogs() {
        try {
          const response = await fetch(API.logs);
          const logs = await response.json();

          const tableBody = logsContainer.querySelector('tbody');
          tableBody.innerHTML = logs.map(log => `
            <tr>
              <td>${log.material}</td>
              <td>
                <span class="badge ${
                  log.confidence === 'High' ? 'bg-success' : 
                  log.confidence === 'Medium' ? 'bg-warning' : 'bg-danger'
                }">${log.confidence}</span>
              </td>
              <td style="font-size: 0.9rem">${new Date(log.timestamp).toLocaleString()}</td>
            </tr>
          `).join('');

          // Search logs
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

      // Update AI classification
      async function updateClassification() {
        try {
          const response = await fetch(API.classification);
          const cls = await response.json();
          const time = new Date(cls.timestamp).toLocaleTimeString();

          classificationResult.innerHTML = `
            <div class="text-center">
              <h4 class="mb-3">Material: <span class="text-primary">${cls.material}</span></h4>
              <p>Confidence: <strong>${cls.confidence}</strong></p>
              <p>Last Detected: <em>${time}</em></p>
              <button class="btn btn-outline-success mt-2" id="rescanBtn">🔁 Rescan</button>
            </div>
          `;
          document.getElementById('rescanBtn').addEventListener('click', updateClassification);
        } catch (error) {
          classificationResult.innerHTML = '<p class="text-danger">Error loading AI result</p>';
        }
      }

      // Update system health
      async function updateHealth() {
        try {
          const response = await fetch(API.health);
          const h = await response.json();

          systemHealth.innerHTML = `
            <div class="d-flex justify-content-between mb-2">
              <span>Camera</span>
              <span class="badge ${h.camera ? 'bg-success' : 'bg-danger'}">
                ${h.camera ? 'Good' : 'Faulty'}
              </span>
            </div>
            <div class="d-flex justify-content-between mb-2">
              <span>Arm Status</span>
              <span class="badge ${h.arm === 'idle' ? 'bg-info' : 'bg-warning'}">${h.arm}</span>
            </div>
            <div class="d-flex justify-content-between mb-2">
              <span>Temperature</span>
              <span class="badge ${h.temperature === 'Normal' ? 'bg-success' : 'bg-danger'}">${h.temperature}</span>
            </div>
            <div class="d-flex justify-content-between">
              <span>Model</span>
              <span class="badge bg-primary">${h.model}</span>
            </div>
          `;
        } catch (error) {
          systemHealth.innerHTML = '<span class="text-danger">Health check failed</span>';
        }
      }

      // Manual log submission
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
          }
        } catch (error) {
          console.error('Log submit error:', error);
        }
      });

      // Logout
      document.getElementById('logoutBtn').addEventListener('click', () => {
        if (confirm('Logout?')) window.location.href = '/logout';
      });

      // Initial load
      updateLogs();
      updateClassification();
      updateHealth();

      // Auto-refresh
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
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        if pico_serial and pico_serial.is_open:
            pico_serial.close()