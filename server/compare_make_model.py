"""Compares the current make/model classifier against a candidate with
broader class coverage (Jordo23/vehicle-classifier, ~8,949 make/model/year
classes) on a real snapshot, so we can decide whether switching is worth it.

The candidate's checkpoint is loaded with torch.load(..., weights_only=True)
so a malicious pickle in the third-party file can't execute arbitrary code -
this only reconstructs plain tensors/dicts/strings, nothing else.

Usage: venv\\Scripts\\python compare_make_model.py path\\to\\snapshot.jpg
"""
import sys

import cv2
import numpy as np
import timm
import torch
from huggingface_hub import hf_hub_download
from PIL import Image

from make_model_classifier import MakeModelClassifier

CANDIDATE_REPO = "Jordo23/vehicle-classifier"
CANDIDATE_CHECKPOINT_FILE = "vehicle_classifier.pth"
CANDIDATE_NUM_CLASSES = 8949
CANDIDATE_INPUT_SIZE = 380
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


def run_current_classifier(crop_bgr):
    result = MakeModelClassifier().classify(crop_bgr)
    print(f"label={result.label!r} confidence={result.confidence:.3f}")


def preprocess_for_candidate(pil_image: Image.Image) -> torch.Tensor:
    resized = pil_image.resize((CANDIDATE_INPUT_SIZE, CANDIDATE_INPUT_SIZE))
    tensor = torch.from_numpy(np.array(resized)).float().permute(2, 0, 1) / 255.0
    return ((tensor - IMAGENET_MEAN) / IMAGENET_STD).unsqueeze(0)


def run_candidate_classifier(pil_image: Image.Image):
    checkpoint_path = hf_hub_download(repo_id=CANDIDATE_REPO, filename=CANDIDATE_CHECKPOINT_FILE)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)

    model = timm.create_model("efficientnet_b4", pretrained=False, num_classes=CANDIDATE_NUM_CLASSES)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    input_tensor = preprocess_for_candidate(pil_image)
    with torch.no_grad():
        probabilities = torch.softmax(model(input_tensor), dim=1)
        top_probs, top_indices = torch.topk(probabilities, 5)

    class_mapping = checkpoint["class_mapping"]
    for prob, idx in zip(top_probs[0], top_indices[0]):
        print(f"{class_mapping[idx.item()]}: {prob.item() * 100:.1f}%")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: compare_make_model.py path\\to\\snapshot.jpg")
    image_path = sys.argv[1]

    crop_bgr = cv2.imread(image_path)
    if crop_bgr is None:
        raise SystemExit(f"could not read {image_path}")

    print(f"=== testing on {image_path} ===\n")
    print("--- current classifier (dima806/car_models_image_detection) ---")
    run_current_classifier(crop_bgr)

    print("\n--- candidate classifier (Jordo23/vehicle-classifier) ---")
    pil_image = Image.open(image_path).convert("RGB")
    run_candidate_classifier(pil_image)


if __name__ == "__main__":
    main()
