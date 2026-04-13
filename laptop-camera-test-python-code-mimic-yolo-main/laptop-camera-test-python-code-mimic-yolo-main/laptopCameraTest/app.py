# app.py - AI Waste Sorter Mimic using Haar Cascades (No YOLO)

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import cv2
import threading
from datetime import datetime
import os

app = FastAPI()

# Create static directory if it doesn't exist
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize camera
camera = cv2.VideoCapture(0)
if not camera.isOpened():
    raise RuntimeError("Could not start camera.")

# Load Haar Cascades
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
mouth_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')

# Debug: Check if classifiers loaded
if face_cascade.empty():
    raise IOError("Face cascade XML file not found!")
if eye_cascade.empty():
    raise IOError("Eye cascade XML file not found!")
if mouth_cascade.empty():
    raise IOError("Mouth cascade XML file not found!")

# Simulated waste labels (for mimicry)
waste_labels = ['Plastic Bottle', 'Paper Waste', 'Food Container', 'Styrofoam Cup']
waste_counter = 0

# Detection history (thread-safe)
detection_history = []
history_lock = threading.Lock()


def generate_frames():
    global waste_counter
    while True:
        success, frame = camera.read()
        if not success:
            break

        # Convert to grayscale for Haar detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 👁️ Detect faces
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(70, 70)
        )

        detected_objects = []

        for (x, y, w, h) in faces:
            # Draw face rectangle and label
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
            cv2.putText(frame, 'Face', (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

            roi_gray = gray[y:y + h, x:x + w]
            roi_color = frame[y:y + h, x:x + w]

            # 👀 Detect eyes
            eyes = eye_cascade.detectMultiScale(
                roi_gray,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(15, 15)
            )
            for (ex, ey, ew, eh) in eyes:
                cv2.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), (0, 255, 0), 2)
                cv2.putText(roi_color, 'Eye', (ex, ey - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # 💬 Detect mouth (as "waste")
            mouths = mouth_cascade.detectMultiScale(
                roi_gray,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(20, 20)
            )
            for (mx, my, mw, mh) in mouths:
                if my > h // 2:  # Only lower half of face
                    # Simulate waste detection
                    label = waste_labels[waste_counter % len(waste_labels)]
                    waste_counter += 1

                    obj_x, obj_y = x + mx, y + my
                    cv2.rectangle(frame, (obj_x, obj_y), (obj_x + mw, obj_y + mh), (0, 255, 0), 2)
                    cv2.putText(frame, f'{label} 94%', (obj_x, obj_y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    detected_objects.append(label)

        # Update detection history
        if detected_objects:
            current_time = datetime.now().strftime("%I:%M %p")
            with history_lock:
                for obj in detected_objects:
                    entry = {"type": obj, "time": current_time, "confidence": "High"}
                    if len(detection_history) >= 4:
                        detection_history.pop()
                    detection_history.insert(0, entry)

        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
        frame_bytes = buffer.tobytes()

        # Yield frame in multipart format
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


@app.get('/video_feed')
async def video_feed():
    return StreamingResponse(
        generate_frames(),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    with history_lock:
        history_items = "".join(
            f'<li><span>{item["type"]}</span> <span>{item["time"]}</span></li>'
            for item in detection_history
        ) or '<li><span>No items yet</span> <span>--:--</span></li>'

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>AI Waste Sorter</title>
      <style>
        body {{
          font-family: 'Segoe UI', sans-serif;
          background-color: #000;
          color: #fff;
          margin: 0;
        }}
        .container {{
          padding: 20px;
        }}
        header {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 2px solid #444;
          padding-bottom: 10px;
        }}
        header h1 {{
          font-size: 24px;
          margin: 0;
        }}
        .status {{
          font-size: 14px;
        }}
        main {{
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 20px;
          margin-top: 20px;
        }}
        .camera-feed {{
          width: 100%;
          border: 2px solid #333;
          background-color: #000;
          display: block;
        }}
        .result-box {{
          background-color: #111;
          padding: 20px;
          border-radius: 8px;
        }}
        .result-label {{
          font-size: 32px;
          margin: 0;
        }}
        .confidence {{
          color: #aaa;
        }}
        .sort-btn {{
          background-color: #2a6ef4;
          color: white;
          padding: 10px 20px;
          border: none;
          margin-top: 10px;
          cursor: pointer;
          border-radius: 4px;
        }}
        .logs ul {{
          list-style: none;
          padding: 0;
        }}
        .logs li {{
          background-color: #111;
          display: flex;
          justify-content: space-between;
          padding: 10px;
          margin-bottom: 6px;
          border-radius: 4px;
        }}
        .controls, .action-buttons {{
          display: flex;
          flex-direction: column;
          gap: 10px;
          align-items: center;
        }}
        .middle-row {{
          display: flex;
          gap: 10px;
        }}
        .arrow, .pick, .drop, .emergency {{
          background-color: #333;
          color: white;
          border: none;
          padding: 12px;
          font-size: 16px;
          cursor: pointer;
          border-radius: 4px;
        }}
        .emergency {{
          background-color: #f44336;
        }}
        .good {{
          color: #4CAF50;
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <header>
          <h1>AI WASTE SORTER</h1>
          <div class="status">
            <span>Camera: <span class="online">Online</span></span>
            <span>Arm: Idle</span>
          </div>
        </header>

        <main>
          <section class="camera-section">
            <h2>Camera Feed</h2>
            <img src="/video_feed" class="camera-feed" width="640" height="480" alt="Live Detection">
          </section>

          <section class="ai-result">
            <h2>AI Detection Result</h2>
            <div class="result-box">
              <p class="result-label">PLASTIC BOTTLE</p>
              <p class="confidence">Detection Confidence: <strong>94%</strong></p>
              <button class="sort-btn">Sort Waste</button>
            </div>
          </section>

          <section class="logs">
            <h2>Detection Logs</h2>
            <ul>
              {history_items}
            </ul>
          </section>

          <section class="controller">
            <h2>Robot Arm Controller</h2>
            <div class="controls">
              <button class="arrow up">↑</button>
              <div class="middle-row">
                <button class="arrow left">←</button>
                <button class="arrow right">→</button>
              </div>
              <button class="arrow down">↓</button>
            </div>
            <div class="action-buttons">
              <button class="pick">Pick Up</button>
              <button class="drop">Drop</button>
              <button class="emergency">Emergency Stop</button>
            </div>
          </section>

          <section class="health">
            <h2>System Health</h2>
            <ul>
              <li><span>Camera</span> <span class="good">Good</span></li>
              <li><span>Detection</span> <span class="good">Good</span></li>
              <li><span>Actuator</span> <span class="good">Good</span></li>
            </ul>
          </section>
        </main>
      </div>
    </body>
    </html>
    """


# Optional: Local OpenCV viewer in separate thread
def run_local_viewer():
    while True:
        success, frame = camera.read()
        if not success:
            break
        cv2.imshow('Live Detection - Press Q to Exit', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    camera.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    import uvicorn

    # Start local viewer in background thread
    viewer_thread = threading.Thread(target=run_local_viewer, daemon=True)
    viewer_thread.start()

    try:
        print("Starting server at http://localhost:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        camera.release()
        cv2.destroyAllWindows()