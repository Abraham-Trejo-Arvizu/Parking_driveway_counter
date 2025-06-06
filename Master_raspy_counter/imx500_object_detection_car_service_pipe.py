import argparse
import json
import sys
import os
import time

import cv2
import numpy as np

from picamera2 import MappedArray, Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics

last_detections = []
frame_counter = 0  # Track frame number
pipe_fd = None  # File descriptor for named pipe

class Detection:
    def __init__(self, coords, category, conf, metadata):
        """Create a Detection object, recording the bounding box, category and confidence."""
        self.category = category
        self.conf = conf
        self.box = imx500.convert_inference_coords(coords, metadata, picam2)

def parse_detections(metadata: dict):
    """Parse the output tensor into a number of detected objects, scaled to the ISP output."""
    global last_detections
    try:
        np_outputs = imx500.get_outputs(metadata, add_batch=True)
        if np_outputs is None:
            return last_detections

        input_w, input_h = imx500.get_input_size()
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]

        if args.bbox_normalization:
            boxes = boxes / input_h

        if args.bbox_order == "xy":
            boxes = boxes[:, [1, 0, 3, 2]]
        boxes = np.array_split(boxes, 4, axis=1)
        boxes = zip(*boxes)

        last_detections = [
            Detection(box, category, score, metadata)
            for box, score, category in zip(boxes, scores, classes)
            if score > args.threshold
        ]
        return last_detections
    except Exception as e:
        print(f"Error parsing detections: {e}", file=sys.stderr)
        return last_detections

def get_labels():
    """Load labels from file, ensuring compatibility with state machine."""
    try:
        labels = intrinsics.labels
        if args.ignore_dash_labels:
            labels = [label for label in labels if label and label != "-"]
        label_map = {i: label for i, label in enumerate(labels)}
        if "car" not in label_map.values() and "Service_car" not in label_map.values():
            print("Warning: Labels do not include 'car' or 'Service_car', may not be compatible with state machine", file=sys.stderr)
        return labels
    except Exception as e:
        print(f"Error loading labels: {e}", file=sys.stderr)
        return []

def draw_detections(request, stream="main"):
    """Draw the detections for this request onto the ISP output."""
    detections = last_results
    if detections is None:
        return
    labels = get_labels()
    try:
        with MappedArray(request, stream) as m:
            for detection in detections:
                x, y, w, h = detection.box
                label = f"{labels[int(detection.category)]} ({float(detection.conf):.2f})"

                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                text_x = x + 5
                text_y = y + 15

                cv2.rectangle(
                    m.array,
                    (text_x, text_y - text_height),
                    (text_x + text_width, text_y + baseline),
                    (255, 255, 255),
                    cv2.FILLED,
                )

                cv2.putText(
                    m.array,
                    label,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),
                    1,
                )

                cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0), thickness=2)

            if args.preserve_aspect_ratio:
                b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request)
                cv2.putText(
                    m.array,
                    "ROI",
                    (b_x + 5, b_y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 0, 0),
                    1,
                )
                cv2.rectangle(
                    m.array, (b_x, b_y), (b_x + b_w, b_y + b_h), (255, 0, 0, 0)
                )
    except Exception as e:
        print(f"Error drawing detections: {e}", file=sys.stderr)

def send_detections(detections):
    """Send detection data as JSON to named pipe."""
    global frame_counter, pipe_fd
    labels = get_labels()
    output = {
        "frame": frame_counter,
        "detections": []
    }

    try:
        for det in detections:
            x, y, w, h = det.box
            output["detections"].append({
                "label": labels[int(det.category)],
                "bbox": [int(x), int(y), int(w), int(h)]
            })

        json_str = json.dumps(output) + "\n"
        if pipe_fd is not None:
            try:
                os.write(pipe_fd, json_str.encode('utf-8'))
            except OSError as e:
                print(f"Pipe write error: {e}, switching to stderr", file=sys.stderr)
                os.close(pipe_fd)
                pipe_fd = None
        if pipe_fd is None:
            print(json_str, file=sys.stderr)

    except Exception as e:
        print(f"Error sending detections: {e}", file=sys.stderr)

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        help="Path of the model",
        default="/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk",
    )
    parser.add_argument("--fps", type=int, help="Frames per second")
    parser.add_argument(
        "--bbox-normalization",
        action=argparse.BooleanOptionalAction,
        help="Normalize bbox",
    )
    parser.add_argument(
        "--bbox-order",
        choices=["yx", "xy"],
        default="yx",
        help="Set bbox order yx -> (y0, x0, y1, x1) xy -> (x0, y0, x1, y1)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.55, help="Detection threshold"
    )
    parser.add_argument("--iou", type=float, default=0.65, help="Set iou threshold")
    parser.add_argument(
        "--max-detections", type=int, default=10, help="Set max detections"
    )
    parser.add_argument(
        "--ignore-dash-labels",
        action=argparse.BooleanOptionalAction,
        help="Remove '-' labels",
    )
    parser.add_argument(
        "--preserve-aspect-ratio",
        action=argparse.BooleanOptionalAction,
        help="Preserve the pixel aspect ratio of the input tensor",
    )
    parser.add_argument("--labels", type=str, help="Path to the labels file")
    parser.add_argument(
        "--pipe",
        type=str,
        default="/tmp/detections.pipe",
        help="Named pipe for JSON output (e.g., /tmp/detections.pipe)"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = get_args()

    try:
        # Initialize named pipe
        pipe_path = args.pipe
        if not os.path.exists(pipe_path):
            os.mkfifo(pipe_path)
            print(f"Created named pipe at {pipe_path}", file=sys.stderr)
        timeout = 10  # seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                pipe_fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                print(f"Opened named pipe {pipe_path} for writing", file=sys.stderr)
                break
            except OSError as e:
                if e.errno != 6:  # ENXIO (no reader)
                    print(f"Pipe error: {e}", file=sys.stderr)
                    pipe_fd = None
                    break
                print(f"Waiting for reader on {pipe_path}...", file=sys.stderr)
                time.sleep(1)
        else:
            print(f"No reader after {timeout}s, using stderr", file=sys.stderr)
            pipe_fd = None

        # Initialize IMX500
        imx500 = IMX500(args.model)
        intrinsics = imx500.network_intrinsics
        if not intrinsics:
            intrinsics = NetworkIntrinsics()
            intrinsics.task = "object detection"
        elif intrinsics.task != "object detection":
            print("Network is not an object detection task", file=sys.stderr)
            sys.exit(1)

        # Load labels
        if args.labels:
            try:
                with open(args.labels, "r") as f:
                    intrinsics.labels = f.read().splitlines()
            except Exception as e:
                print(f"Error reading labels file: {e}", file=sys.stderr)
                sys.exit(1)
        elif intrinsics.labels is None:
            try:
                intrinsics.labels = ["car", "Service_car"]
            except Exception as e:
                print(f"Error reading default labels: {e}", file=sys.stderr)
                sys.exit(1)

        # Override intrinsics from args
        for key, value in vars(args).items():
            if key != "labels" and hasattr(intrinsics, key) and value is not None:
                setattr(intrinsics, key, value)

        intrinsics.update_with_defaults()

        # Initialize camera
        picam2 = Picamera2(imx500.camera_num)
        config = picam2.create_preview_configuration(
            controls={"FrameRate": args.fps or intrinsics.inference_rate},
            buffer_count=12,
        )

        imx500.show_network_fw_progress_bar()
        picam2.start(config, show_preview=True)

        if args.preserve_aspect_ratio:
            imx500.set_auto_aspect_ratio()

        last_results = None
        picam2.pre_callback = draw_detections

        while True:
            try:
                last_results = parse_detections(picam2.capture_metadata())
                frame_counter += 1
                send_detections(last_results)
            except Exception as e:
                print(f"Main loop error: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("Shutting down...")
    except Exception as e:
        print(f"Initialization error: {e}", file=sys.stderr)
    finally:
        try:
            if pipe_fd is not None:
                os.close(pipe_fd)
            if os.path.exists(pipe_path):
                os.unlink(pipe_path)
                print(f"Removed named pipe {pipe_path}", file=sys.stderr)
            picam2.stop()
            picam2.close()
        except Exception as e:
            print(f"Cleanup error: {e}", file=sys.stderr)