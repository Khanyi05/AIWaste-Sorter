# camera_calibration.py - FIXED INPUT HANDLING
import cv2
import numpy as np
import json
import time
import serial
import serial.tools.list_ports


class TeachModeCalibrator:
    def __init__(self):
        self.calibration_points = []  # (pixel_x, pixel_y, real_x_cm, real_y_cm)
        self.camera = cv2.VideoCapture(0)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.current_real_position = None
        self.serial_connection = None

        # YOUR CALIBRATED POSITIONS FROM robot_arm_pico.py
        self.known_positions = {
            '1': {'name': '(29,29)', 'real_x': 29, 'real_y': 29, 'command': 'G'},
            '2': {'name': '(22,22)', 'real_x': 22, 'real_y': 22, 'command': 'H'},
            '3': {'name': '(23,21)', 'real_x': 23, 'real_y': 21, 'command': 'J'},
            '4': {'name': '(15,30)', 'real_x': 15, 'real_y': 30, 'command': 'K'}
        }

        # Initialize serial connection to Pico
        self._connect_to_pico()

    def _connect_to_pico(self):
        """Connect to the Pico via serial"""
        try:
            ports = serial.tools.list_ports.comports()
            pico_port = None

            for port in ports:
                if "Pico" in port.description or "USB Serial Device" in port.description:
                    pico_port = port.device
                    break

            if pico_port:
                self.serial_connection = serial.Serial(
                    pico_port,
                    baudrate=115200,
                    timeout=1,
                    write_timeout=1
                )
                time.sleep(2)  # Wait for Pico to initialize
                print(f"✅ Connected to Pico at {pico_port}")

                # Test communication
                self.serial_connection.write(b'?\n')
                self.serial_connection.flush()
                time.sleep(1)
                if self.serial_connection.in_waiting > 0:
                    response = self.serial_connection.readline().decode('utf-8').strip()
                    print(f"📡 Pico test response: {response}")

            else:
                print("❌ Pico not found - using manual mode")
                print("💡 You'll need to manually send commands when prompted")

        except Exception as e:
            print(f"❌ Serial connection failed: {e}")
            print("💡 You'll need to manually send commands when prompted")

    def _send_to_pico(self, command):
        """Send command to Pico and wait for response"""
        if self.serial_connection and self.serial_connection.is_open:
            try:
                # Clear buffer
                self.serial_connection.reset_input_buffer()

                # Send command
                full_cmd = command + '\n'
                print(f"📤 Sending command: '{command}' to Pico...")
                self.serial_connection.write(full_cmd.encode('utf-8'))
                self.serial_connection.flush()

                # Wait for response
                start_time = time.time()
                response_received = False
                while time.time() - start_time < 10:  # 10 second timeout
                    if self.serial_connection.in_waiting > 0:
                        response = self.serial_connection.readline().decode('utf-8').strip()
                        if response:
                            print(f"📥 Pico response: {response}")
                            response_received = True
                            break
                    time.sleep(0.1)

                if not response_received:
                    print("⚠️ No response from Pico, but command sent")

                # Wait for movement to complete
                print("⏳ Waiting for movement to complete...")
                time.sleep(4)  # Give time for full movement
                return True

            except Exception as e:
                print(f"❌ Serial error: {e}")
                return False
        else:
            print("⚠️ No serial connection - manual mode")
            return False

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and self.current_real_position:
            real_x, real_y = self.current_real_position
            self.calibration_points.append((x, y, real_x, real_y))
            print(f"✅ Added: pixel({x}, {y}) -> real({real_x}cm, {real_y}cm)")
            print(f"Total calibration points: {len(self.calibration_points)}")

            # Clear current position after adding
            self.current_real_position = None

    def run_teach_mode(self):
        print("🎯 TEACH MODE CALIBRATION - USING KNOWN ROBOT POSITIONS")
        print("=" * 60)
        print("INSTRUCTIONS:")
        print("1. Choose a position number (1-4) from the list below")
        print("2. Robot will AUTOMATICALLY move to that position")
        print("3. Wait for movement to complete")
        print("4. Click on the gripper tip in the camera view")
        print("5. Repeat for all positions")
        print("6. Press 'c' to calibrate when done")
        print("7. Press 'q' to quit")
        print("=" * 60)
        print("KNOWN POSITIONS:")
        for key, pos in self.known_positions.items():
            print(f"  {key}. {pos['name']} - Real: ({pos['real_x']}cm, {pos['real_y']}cm)")
        print("=" * 60)

        cv2.namedWindow("Teach Mode Calibration")
        cv2.setMouseCallback("Teach Mode Calibration", self.mouse_callback)

        while True:
            ret, frame = self.camera.read()
            if not ret:
                print("❌ Failed to read from camera")
                break

            # Draw existing calibration points
            for i, (px, py, rx, ry) in enumerate(self.calibration_points):
                cv2.circle(frame, (px, py), 8, (0, 255, 0), -1)
                cv2.putText(frame, f"({rx},{ry})cm", (px + 10, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(frame, str(i + 1), (px - 5, py + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Draw crosshair at current position if set
            if self.current_real_position:
                cv2.putText(frame, "CLICK ON GRIPPER TIP NOW!", (150, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.putText(frame, f"Real position: {self.current_real_position}cm", (150, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # Instructions overlay
            cv2.putText(frame, "Press 1-4 to move robot | 'c' to calibrate | 'q' to quit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(frame, f"Calibration points: {len(self.calibration_points)}/4",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Show connection status
            status = "Connected" if self.serial_connection else "Manual Mode"
            color = (0, 255, 0) if self.serial_connection else (0, 255, 255)
            cv2.putText(frame, f"Pico: {status}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            cv2.imshow("Teach Mode Calibration", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in [ord('1'), ord('2'), ord('3'), ord('4')]:
                position_key = chr(key)
                self.move_to_known_position(position_key)
            elif key == ord('c') and len(self.calibration_points) >= 3:
                self.perform_calibration()
            elif key == ord('q'):
                break

        if self.serial_connection:
            self.serial_connection.close()
        self.camera.release()
        cv2.destroyAllWindows()

    def move_to_known_position(self, position_key):
        """Move robot to one of your known calibrated positions"""
        if position_key in self.known_positions:
            position = self.known_positions[position_key]
            real_x, real_y = position['real_x'], position['real_y']
            command = position['command']

            print(f"\n🤖 MOVING ROBOT TO {position['name']}...")
            print(f"📏 Real position: ({real_x}cm, {real_y}cm)")
            print(f"🔧 Sending command: '{command}'")

            # Set current position for clicking
            self.current_real_position = (real_x, real_y)

            # Send command to Pico
            success = self._send_to_pico(command)

            if success:
                print("✅ Robot movement completed!")
                print("🎯 NOW CLICK ON THE GRIPPER TIP IN THE CAMERA VIEW!")
            else:
                print("❌ Failed to send command to robot")
                print("💡 Please manually move the robot to this position using your main.py")
                manual_input = input("Press Enter after you've manually moved the robot, or 's' to skip: ")
                if manual_input.lower() == 's':
                    self.current_real_position = None
        else:
            print("❌ Invalid position key")

    def perform_calibration(self):
        print("\n🔧 Performing calibration with your known positions...")

        if len(self.calibration_points) < 3:
            print("❌ Need at least 3 calibration points")
            return

        # Extract coordinates
        pixels = np.array([[x, y] for x, y, _, _ in self.calibration_points], dtype=np.float32)
        real_coords = np.array([[x, y] for _, _, x, y in self.calibration_points], dtype=np.float32)

        print(f"📐 Calibrating with {len(pixels)} points:")
        for i, (px, py, rx, ry) in enumerate(self.calibration_points):
            print(f"  Point {i + 1}: pixel({px}, {py}) -> real({rx}, {ry})")

        # Calculate transformation
        transform_matrix, _ = cv2.estimateAffinePartial2D(pixels, real_coords)

        if transform_matrix is not None:
            # Test accuracy
            total_error = 0
            max_error = 0
            print("\n📊 CALIBRATION ACCURACY REPORT:")
            print("Point | Pixel Coord | Real Coord | Predicted Coord | Error (cm)")
            print("-" * 65)

            for i, (px, py, rx, ry) in enumerate(self.calibration_points):
                # Transform pixel to real
                pixel_arr = np.array([[px, py]], dtype=np.float32)
                predicted = cv2.transform(pixel_arr.reshape(1, -1, 2), transform_matrix)
                pred_x, pred_y = predicted[0, 0, 0], predicted[0, 0, 1]

                error = np.sqrt((pred_x - rx) ** 2 + (pred_y - ry) ** 2)
                total_error += error
                max_error = max(max_error, error)

                print(
                    f"{i + 1:2d}   | ({px:2.0f},{py:2.0f})     | ({rx:2.0f},{ry:2.0f})     | ({pred_x:4.1f},{pred_y:4.1f}) | {error:5.2f} cm")

            avg_error = total_error / len(self.calibration_points)
            print("-" * 65)
            print(f"📈 Average error: {avg_error:.2f} cm")
            print(f"📈 Maximum error: {max_error:.2f} cm")

            # Save calibration
            calibration_data = {
                'transform_matrix': transform_matrix.tolist(),
                'calibration_points': self.calibration_points,
                'known_positions': self.known_positions,
                'avg_error': avg_error,
                'max_error': max_error,
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
            }

            with open('robot_calibration.json', 'w') as f:
                json.dump(calibration_data, f, indent=2)

            print("💾 Calibration saved to 'robot_calibration.json'")

            if avg_error < 2.0:
                print("✅ Excellent calibration accuracy!")
            elif avg_error < 5.0:
                print("⚠️  Good calibration accuracy")
            else:
                print("❌ Poor accuracy - check your points")

            self.test_calibration(transform_matrix)
        else:
            print("❌ Calibration failed - points may be colinear")

    def test_calibration(self, transform_matrix):
        print("\n🧪 TEST MODE: Click anywhere to see predicted real coordinates")
        print("Press 'q' to exit test mode")

        def test_mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                pixel_arr = np.array([[x, y]], dtype=np.float32)
                real_coords = cv2.transform(pixel_arr.reshape(1, -1, 2), transform_matrix)
                real_x, real_y = real_coords[0, 0, 0], real_coords[0, 0, 1]
                print(f"Pixel({x}, {y}) -> Real({real_x:.1f}cm, {real_y:.1f}cm)")

        cv2.namedWindow("Test Calibration")
        cv2.setMouseCallback("Test Calibration", test_mouse_callback)

        while True:
            ret, frame = self.camera.read()
            if not ret:
                break

            # Draw calibration points for reference
            for px, py, rx, ry in self.calibration_points:
                cv2.circle(frame, (px, py), 6, (0, 255, 0), -1)

            cv2.putText(frame, "Click to test coordinates | 'q' to quit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imshow("Test Calibration", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        self.camera.release()
        cv2.destroyAllWindows()



if __name__ == "__main__":
    print("🤖 TEACH MODE CALIBRATION - WITH AUTOMATIC ROBOT CONTROL")
    print("Make sure your Pico is connected via USB and running robot_arm_pico.py")

    input("Press Enter to start calibration...")

    calibrator = TeachModeCalibrator()
    calibrator.run_teach_mode()