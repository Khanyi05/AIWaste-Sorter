# visual_calibration.py - Interactive calibration with camera feed
import cv2
import numpy as np
import json


class VisualCalibrator:
    def __init__(self):
        self.calibration_points = []
        self.camera = cv2.VideoCapture(0)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            real_x = float(input(f"Enter REAL X coordinate (cm) for pixel ({x}, {y}): "))
            real_y = float(input(f"Enter REAL Y coordinate (cm) for pixel ({x}, {y}): "))

            self.calibration_points.append((x, y, real_x, real_y))
            print(f"✅ Added point: pixel({x}, {y}) -> real({real_x}cm, {real_y}cm)")
            print(f"Total points: {len(self.calibration_points)}")

    def run_calibration(self):
        print("🎯 Visual Calibration Tool")
        print("1. Place a known object in camera view")
        print("2. Click on the object in the camera feed")
        print("3. Enter the REAL world coordinates in cm")
        print("4. Collect at least 6 points around the workspace")
        print("5. Press 'c' to calibrate, 'q' to quit")

        cv2.namedWindow("Calibration")
        cv2.setMouseCallback("Calibration", self.mouse_callback)

        while True:
            ret, frame = self.camera.read()
            if not ret:
                break

            # Draw existing calibration points
            for i, (px, py, rx, ry) in enumerate(self.calibration_points):
                cv2.circle(frame, (px, py), 8, (0, 255, 0), -1)
                cv2.putText(frame, f"({rx},{ry})cm", (px + 10, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(frame, str(i + 1), (px - 5, py + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Instructions
            cv2.putText(frame, "Click to add point | 'c' to calibrate | 'q' to quit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(frame, f"Points: {len(self.calibration_points)}",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            cv2.imshow("Calibration", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('c') and len(self.calibration_points) >= 4:
                self.perform_calibration()
            elif key == ord('q'):
                break

        self.camera.release()
        cv2.destroyAllWindows()

    def perform_calibration(self):
        print("\n🔧 Performing calibration...")

        # Extract coordinates
        pixels = np.array([[x, y] for x, y, _, _ in self.calibration_points], dtype=np.float32)
        real_coords = np.array([[x, y] for _, _, x, y in self.calibration_points], dtype=np.float32)

        # Calculate transformation
        transform_matrix, _ = cv2.estimateAffinePartial2D(pixels, real_coords)

        if transform_matrix is not None:
            # Test accuracy
            total_error = 0
            print("\n📊 Calibration Results:")
            for i, (px, py, rx, ry) in enumerate(self.calibration_points):
                # Transform pixel to real
                pixel_arr = np.array([[px, py]], dtype=np.float32)
                predicted = cv2.transform(pixel_arr.reshape(1, -1, 2), transform_matrix)
                pred_x, pred_y = predicted[0, 0, 0], predicted[0, 0, 1]

                error = np.sqrt((pred_x - rx) ** 2 + (pred_y - ry) ** 2)
                total_error += error
                print(f"Point {i + 1}: error = {error:.2f} cm")

            avg_error = total_error / len(self.calibration_points)
            print(f"📈 Average error: {avg_error:.2f} cm")

            if avg_error < 2.0:  # Good accuracy threshold
                # Save calibration
                calibration_data = {
                    'transform_matrix': transform_matrix.tolist(),
                    'calibration_points': self.calibration_points,
                    'avg_error': avg_error
                }

                with open('visual_calibration.json', 'w') as f:
                    json.dump(calibration_data, f, indent=2)

                print("💾 Calibration saved to 'visual_calibration.json'")

                # Test the calibration
                self.test_calibration(transform_matrix)
            else:
                print("❌ Poor accuracy - add more calibration points")
        else:
            print("❌ Calibration failed")

    def test_calibration(self, transform_matrix):
        print("\n🧪 Testing calibration - click on points to see real coordinates")

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

            cv2.putText(frame, "Click to test coordinates | 'q' to quit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imshow("Test Calibration", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        self.camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    calibrator = VisualCalibrator()
    calibrator.run_calibration()