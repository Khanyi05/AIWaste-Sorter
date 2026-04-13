# train_waste_detector.py
# ✅ Updated with working dataset URL

import os
import requests
import zipfile
import yaml
from pathlib import Path
from ultralytics import YOLO


# ========================
# 1. Configuration
# ========================
DATASET_URL = "https://public.roboflow.com/ds/ZqEJ9giuBC~6CjLJ34Y6Cn-1.zip?model=yolov8"  # Direct download link
DATASET_ZIP = "waste_dataset.zip"
DATASET_DIR = "waste_dataset"

# Only keep: plastic, glass, paper
CLASS_NAMES = ["plastic", "glass", "paper"]
NC = 3  # 3 classes

# Training settings
EPOCHS = 50
IMGSZ = 640
BATCH = 16
MODEL_NAME = "waste_sorter_v1"


# ========================
# 2. Download Dataset
# ========================
def download_dataset():
    print("📥 Downloading waste detection dataset...")
    try:
        response = requests.get(DATASET_URL, stream=True)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print("❌ Failed to download dataset. Check your internet or the URL.")
        print("💡 Tip: Try opening this link in your browser to test:")
        print("   https://universe.roboflow.com/waste-detection-rdorc/plastic-glass-paper-waste-detection")
        raise e

    with open(DATASET_ZIP, "wb") as f:
        downloaded = 0
        total = int(response.headers.get('content-length', 0))
        print(f"💾 Total size: {total // 1024 // 1024} MB")
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                done = int(50 * downloaded / total)
                print(f"\rProgress: [{'=' * done}{' ' * (50-done)}] {100*downloaded/total:.1f}%", end='')
        print()

    print(f"✅ Dataset downloaded: {DATASET_ZIP}")


# ========================
# 3. Extract Dataset
# ========================
def extract_dataset():
    print("📦 Extracting dataset...")
    if os.path.exists(DATASET_DIR):
        print(f"⚠️  Found existing {DATASET_DIR}, skipping extraction")
        return

    with zipfile.ZipFile(DATASET_ZIP, 'r') as zip_ref:
        zip_ref.extractall(DATASET_DIR)
    print(f"✅ Extracted to: {DATASET_DIR}")


# ========================
# 4. Create data.yaml
# ========================
def create_data_yaml():
    print("📄 Creating data.yaml...")
    data = {
        'train': f'./{DATASET_DIR}/train/images',
        'val': f'./{DATASET_DIR}/valid/images',
        'test': f'./{DATASET_DIR}/test/images',
        'nc': NC,
        'names': CLASS_NAMES
    }
    with open("data.yaml", "w") as f:
        yaml.dump(data, f, default_flow_style=None, sort_keys=False)
    print("✅ data.yaml created")


# ========================
# 5. Train YOLOv8 Model
# ========================
def train_model():
    print("🚀 Starting training...")
    model = YOLO("yolov8n.pt")  # Load pre-trained nano model

    results = model.train(
        data="data.yaml",
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        name=MODEL_NAME,
        project="runs",
        exist_ok=True
    )

    print("✅ Training completed!")
    return model


# ========================
# 6. Validate & Show Results
# ========================
def validate_model(model):
    print("📊 Validating model...")
    metrics = model.val()
    map50 = metrics.box.map50
    map50_to_95 = metrics.box.map

    print("\n" + "="*50)
    print("✅ TRAINING COMPLETE")
    print(f"📦 Model saved at: runs/detect/{MODEL_NAME}/weights/best.pt")
    print(f"📈 mAP@50:        {map50:.3f}")
    print(f"📈 mAP@50:95:     {map50_to_95:.3f}")
    print("="*50)

    return map50, map50_to_95


# ========================
# 7. Main Pipeline
# ========================
def main():
    print("🤖 Starting Custom Waste Detector Training Pipeline")

    # Step 1: Download
    if not os.path.exists(DATASET_ZIP):
        download_dataset()
    else:
        print(f"✅ Found existing {DATASET_ZIP}, skipping download")

    # Step 2: Extract
    extract_dataset()

    # Step 3: Create YAML
    create_data_yaml()

    # Step 4: Train
    model = train_model()

    # Step 5: Validate
    validate_model(model)

    print("\n🎉 You can now use 'runs/detect/waste_sorter_v1/weights/best.pt' in your app!")


# ========================
# Run It!
# ========================
if __name__ == "__main__":
    main()