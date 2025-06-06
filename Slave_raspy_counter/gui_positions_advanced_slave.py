import json
import sys
import os
import tkinter as tk
from tkinter import Canvas
import hashlib
import select
import requests

# Flask server URL (master Pi)
FLASK_SERVER_URL = "http://192.168.191.34:5000/update_passed"

def send_total_passed(total_cars_passed):
    """Send total_cars_passed to the master Flask server."""
    try:
        payload = {
            "role": "exit",
            "total_cars_passed": total_cars_passed
        }
        response = requests.post(FLASK_SERVER_URL, json=payload, timeout=2)
        if response.status_code != 200:
            print(f"Error sending total_cars_passed to Flask: {response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to send total_cars_passed: {e}", file=sys.stderr)

# Read JSON from named pipe
class PipeReader:
    def __init__(self, pipe_path):
        self.pipe_path = pipe_path
        self.pipe = None
        self.fd = None

    def connect(self):
        try:
            if not os.path.exists(self.pipe_path):
                print(f"Named pipe {self.pipe_path} does not exist", file=sys.stderr)
                return False
            self.pipe = open(self.pipe_path, 'r')
            self.fd = self.pipe.fileno()
            print(f"Opened pipe {self.pipe_path} for reading", file=sys.stderr)
            return True
        except Exception as e:
            print(f"Error opening pipe {self.pipe_path}: {e}", file=sys.stderr)
            return False

    def read(self):
        if self.pipe is None:
            if not self.connect():
                return {}
        try:
            if select.select([self.fd], [], [], 0)[0]:
                line = self.pipe.readline().strip()
                if line:
                    return json.loads(line)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Read error: {e}", file=sys.stderr)
        return {}

    def close(self):
        if self.pipe:
            self.pipe.close()
            print(f"Closed pipe {self.pipe_path}", file=sys.stderr)
        self.pipe = None
        self.fd = None

    def fileno(self):
        return self.fd if self.fd is not None else -1

# Info GUI
class InfoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Car Info")
        self.root.geometry("400x500")
        self.current_state = "zero_cars"
        self.car1_data = None
        self.car2_data = None
        self.aoi_active_frames = [0, 0, 0]
        self.current_frame = 0
        self.total_cars_passed = 0
        self.probable_pass_start_frame = 0
        self.right_active_duration = 0
        self.empty_frame_count = 0
        self.one_car_frame_count = 0
        self.one_car_duration = 0
        self.last_processed_frame = -1
        self.pipe_reader = PipeReader("/tmp/detections.pipe")

        self.state_label = tk.Label(root, text="State: zero_cars", font=("Arial", 12))
        self.state_label.pack(pady=5)

        self.num_cars_label = tk.Label(root, text="num cars: 0", font=("Arial", 12))
        self.num_cars_label.pack(pady=5)

        self.total_cars_label = tk.Label(root, text="Total Cars Passed: 0", font=("Arial", 12))
        self.total_cars_label.pack(pady=5)

        self.car1_label = tk.Label(root, text="car(1):\n    +active AOIs: []\n    +coordinates: None", font=("Arial", 12))
        self.car1_label.pack(pady=5, anchor="w")

        self.car2_label = tk.Label(root, text="car(2):\n    +active AOIs: []\n    +coordinates: None", font=("Arial", 12))
        self.car2_label.pack(pady=5, anchor="w")

        self.color_box = tk.Canvas(root, width=79, height=79, bg="#FFFFFF", highlightthickness=1, highlightbackground="black")
        self.color_box.place(x=300, y=20)

    def update(self, num_cars, car1_data, car2_data, state):
        self.state_label.config(text=f"State: {state}")
        self.num_cars_label.config(text=f"num cars: {num_cars}")
        self.total_cars_label.config(text=f"Total Cars Passed: {self.total_cars_passed}")
        car1_text = "car(1):\n    +active AOIs: []\n    +coordinates: None"
        if car1_data:
            car1_text = f"car(1):\n    +active AOIs: {car1_data['active_aois']}\n    +coordinates: {car1_data['bbox']}"
        self.car1_label.config(text=car1_text)
        car2_text = "car(2):\n    +active AOIs: []\n    +coordinates: None"
        if car2_data:
            car2_text = f"car(2):\n    +active AOIs: {car2_data['active_aois']}\n    +coordinates: {car2_data['bbox']}"
        self.car2_label.config(text=car2_text)
        box_color = "#FFFFFF"
        if state == "right_state":
            box_color = "#00FF00"
        elif state == "left_state":
            box_color = "#0000FF"
        self.color_box.config(bg=box_color)
        self.root.update()

    def close(self):
        self.pipe_reader.close()

# Box GUI
class BoxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Box Visualization")
        self.root.geometry("640x480")
        self.canvas = Canvas(root, width=640, height=480, bg="black")
        self.canvas.pack()
        self.aois = [
            {"name": "Left", "box": [20, 165, 8, 150]},
            {"name": "Middle", "box": [316, 165, 8, 150]},
            {"name": "Right", "box": [612, 165, 8, 150]}
        ]

    def update(self, cars, aoi_states):
        self.canvas.delete("all")
        for aoi, active in zip(self.aois, aoi_states):
            x, y, w, h = aoi["box"]
            color = "#00FF00" if active else "#FF0000"
            self.canvas.create_rectangle(x, y, x + w, y + h, outline=color, width=2)
        for car in cars:
            x, y, w, h = car["bbox"]
            car_id = car["id"]
            self.canvas.create_rectangle(x, y, x + w, y + h, outline="#800080", width=2)
            self.canvas.create_text(x + 5, y + 15, text=str(car_id), fill="white", font=("Arial", 10))
        self.root.update()

# Process frame
def process_frame(info_gui, box_gui):
    frame_data = info_gui.pipe_reader.read()
    if not frame_data or "frame" not in frame_data:
        info_gui.root.after(20, process_frame, info_gui, box_gui)
        return

    info_gui.current_frame = frame_data["frame"]
    json_frame_number = info_gui.current_frame

    # Handle frame gaps
    if info_gui.last_processed_frame != -1 and json_frame_number > info_gui.last_processed_frame + 1:
        gap = json_frame_number - info_gui.last_processed_frame - 1
        info_gui.empty_frame_count += gap
    info_gui.last_processed_frame = json_frame_number

    # Extract detections
    detections = frame_data.get("detections", [])
    current_cars = []
    for item in detections:
        if isinstance(item, dict) and "label" in item and item["label"] in ["car", "Service_car"]:
            bbox = item.get("bbox")
            if bbox and len(bbox) == 4:
                rounded_bbox = [round(coord, 1) for coord in bbox]
                current_cars.append({"bbox": rounded_bbox})
    print(f"Frame {json_frame_number}: Raw cars: {current_cars}", file=sys.stderr)

    # Clean overlaps
    sorted_cars = sorted(current_cars, key=lambda c: c["bbox"][0])
    if len(sorted_cars) == 2 and rectangles_overlap(sorted_cars[0]["bbox"], sorted_cars[1]["bbox"]) > 0.5:
        kept_car = sorted_cars[1]
        current_cars = [kept_car]
    else:
        current_cars = sorted_cars[:2]
    raw_num_cars = len(current_cars)
    print(f"Frame {json_frame_number}: Cleaned cars: {current_cars}", file=sys.stderr)

    # Track cars
    new_car1_data = None
    new_car2_data = None
    seen_car_ids = set()

    if raw_num_cars >= 1:
        car1_bbox = current_cars[0]["bbox"]
        car1_id = None
        if info_gui.car1_data and rectangles_overlap(car1_bbox, info_gui.car1_data["bbox"]) > 0.5:
            car1_id = info_gui.car1_data["id"]
        else:
            car1_id = hashlib.md5(str(car1_bbox).encode()).hexdigest()[:8]
        seen_car_ids.add(car1_id)
        new_car1_data = {
            "id": car1_id,
            "bbox": car1_bbox,
            "last_seen_frame": info_gui.current_frame,
            "absent_frames": 0,
            "active_aois": []
        }
    if raw_num_cars == 2:
        car2_bbox = current_cars[1]["bbox"]
        car2_id = None
        if info_gui.car2_data and rectangles_overlap(car2_bbox, info_gui.car2_data["bbox"]) > 0.5:
            car2_id = info_gui.car2_data["id"]
        else:
            car2_id = hashlib.md5(str(car2_bbox).encode()).hexdigest()[:8]
        seen_car_ids.add(car2_id)
        new_car2_data = {
            "id": car2_id,
            "bbox": car2_bbox,
            "last_seen_frame": info_gui.current_frame,
            "absent_frames": 0,
            "active_aois": []
        }

    not_active_obj_car1 = False
    not_active_obj_car2 = False
    if info_gui.car1_data and info_gui.car1_data["id"] not in seen_car_ids:
        new_car1_data = {
            "id": info_gui.car1_data["id"],
            "bbox": info_gui.car1_data["bbox"],
            "last_seen_frame": info_gui.car1_data["last_seen_frame"],
            "absent_frames": info_gui.car1_data["absent_frames"] + 1,
            "active_aois": []
        }
        if new_car1_data["absent_frames"] >= 6:
            not_active_obj_car1 = True
            print(f"Frame {json_frame_number}: Clearing Car1, absent for {new_car1_data['absent_frames']} frames", file=sys.stderr)
    if info_gui.car2_data and info_gui.car2_data["id"] not in seen_car_ids:
        new_car2_data = {
            "id": info_gui.car2_data["id"],
            "bbox": info_gui.car2_data["bbox"],
            "last_seen_frame": info_gui.car2_data["last_seen_frame"],
            "absent_frames": info_gui.car2_data["absent_frames"] + 1,
            "active_aois": []
        }
        if new_car2_data["absent_frames"] >= 6:
            not_active_obj_car2 = True
            print(f"Frame {json_frame_number}: Clearing Car2, absent for {new_car2_data['absent_frames']} frames", file=sys.stderr)

    info_gui.car1_data = None if not_active_obj_car1 else new_car1_data
    info_gui.car2_data = None if not_active_obj_car2 else new_car2_data

    # Update empty_frame_count based on raw detections
    if raw_num_cars == 0:
        info_gui.empty_frame_count += 1
        info_gui.one_car_frame_count = 0
    elif raw_num_cars == 1:
        info_gui.one_car_frame_count += 1
        info_gui.empty_frame_count = 0
    else:
        info_gui.one_car_frame_count = 0
        info_gui.empty_frame_count = 0

    num_cars = 0
    if info_gui.car1_data:
        num_cars += 1
    if info_gui.car2_data:
        num_cars += 1

    if num_cars == 1:
        info_gui.one_car_duration += 1
    else:
        info_gui.one_car_duration = 0

    cars = []
    if info_gui.car1_data:
        cars.append({"id": 1, "bbox": info_gui.car1_data["bbox"]})
    if info_gui.car2_data:
        cars.append({"id": 2, "bbox": info_gui.car2_data["bbox"]})
    print(f"Frame {json_frame_number}: Final num_cars: {num_cars}", file=sys.stderr)

    # Initialize AOI states
    aoi_states = [False] * len(box_gui.aois)
    if info_gui.car1_data:
        info_gui.car1_data["active_aois"] = []
    if info_gui.car2_data:
        info_gui.car2_data["active_aois"] = []

    # Update AOI states based on car positions
    for car in cars:
        car_data = info_gui.car1_data if car["id"] == 1 else info_gui.car2_data
        for i, aoi in enumerate(box_gui.aois):
            if rectangles_overlap(car["bbox"], aoi["box"]) > 0:
                aoi_states[i] = True
                info_gui.aoi_active_frames[i] = info_gui.current_frame
                if car_data:
                    car_data["active_aois"].append(aoi["name"])

    # Persist AOI states for 5 frames
    for i in range(len(aoi_states)):
        if info_gui.current_frame - info_gui.aoi_active_frames[i] <= 5:
            aoi_states[i] = True

    new_state = info_gui.current_state
    match info_gui.current_state:
        case "zero_cars":
            if num_cars == 1:
                new_state = "one_car"
            elif num_cars == 2:
                new_state = "two_cars"
        case "one_car":
            if num_cars == 0 and not info_gui.car1_data:
                new_state = "zero_cars"
            elif num_cars == 2:
                new_state = "two_cars"
            elif info_gui.car1_data and set(info_gui.car1_data["active_aois"]) == {"Left", "Middle", "Right"}:
                new_state = "night_pass"
            elif info_gui.car1_data and "Left" in info_gui.car1_data["active_aois"]:
                new_state = "left_state"
            elif info_gui.car1_data and "Right" in info_gui.car1_data["active_aois"]:
                new_state = "right_state"
        case "night_pass":
            if num_cars == 0 and info_gui.empty_frame_count >= 7:
                info_gui.total_cars_passed += 1
                send_total_passed(info_gui.total_cars_passed)
                new_state = "zero_cars"
                print(f"Frame {json_frame_number}: Exiting night_pass, car passed", file=sys.stderr)
        case "two_cars":
            if info_gui.one_car_duration >= 5 and info_gui.car1_data:
                if info_gui.current_frame - info_gui.aoi_active_frames[2] > 5:
                    new_state = "probable_pass"
                elif info_gui.current_frame - info_gui.aoi_active_frames[0] > 5:
                    info_gui.total_cars_passed += 1
                    send_total_passed(info_gui.total_cars_passed)
                    new_state = "probable_pass"
        case "right_state":
            if num_cars == 0 and not info_gui.car1_data:
                new_state = "zero_cars"
            elif (info_gui.car2_data and
                  ("Left" in info_gui.car2_data["active_aois"] or
                   "Middle" in info_gui.car2_data["active_aois"]) and
                  num_cars > 1):
                new_state = "2_cars_left"
            elif info_gui.current_frame - info_gui.aoi_active_frames[2] > 5:
                new_state = "zero_cars"
            elif (info_gui.car1_data and
                  ("Left" in info_gui.car1_data["active_aois"] or
                   "Middle" in info_gui.car1_data["active_aois"]) and
                  num_cars <= 1):
                if info_gui.probable_pass_start_frame == 0:
                    info_gui.probable_pass_start_frame = info_gui.current_frame
                elif info_gui.current_frame - info_gui.probable_pass_start_frame > 5:
                    new_state = "probable_pass"
            else:
                info_gui.probable_pass_start_frame = 0
        case "left_state":
            if info_gui.current_frame - info_gui.aoi_active_frames[0] > 5:
                new_state = "zero_cars"
            elif (info_gui.car2_data and
                  ("Right" in info_gui.car2_data["active_aois"] or
                   "Middle" in info_gui.car2_data["active_aois"]) and
                  num_cars > 1):
                new_state = "2_cars_left"
        case "probable_pass":
            if num_cars == 0 or not_active_obj_car1:
                if info_gui.probable_pass_start_frame == 0:
                    info_gui.probable_pass_start_frame = info_gui.current_frame
                elif info_gui.current_frame - info_gui.probable_pass_start_frame > 5:
                    info_gui.total_cars_passed += 1
                    send_total_passed(info_gui.total_cars_passed)
                    new_state = "zero_cars"
                    info_gui.probable_pass_start_frame = 0
                    print(f"Frame {json_frame_number}: Exiting probable_pass, car passed", file=sys.stderr)
            elif (num_cars == 2 and info_gui.car2_data and
                  "Right" in info_gui.car2_data["active_aois"]):
                if info_gui.right_active_duration == 0:
                    info_gui.right_active_duration = info_gui.current_frame
                elif info_gui.current_frame - info_gui.right_active_duration > 5:
                    new_state = "two_cars"
                    info_gui.right_active_duration = 0
            else:
                if info_gui.empty_frame_count >= 6:
                    print(f"Frame {json_frame_number}: Timing out probable_pass, no detections for {info_gui.empty_frame_count} frames", file=sys.stderr)
                    new_state = "zero_cars"
                    info_gui.probable_pass_start_frame = 0
                    info_gui.car1_data = None
                    info_gui.car2_data = None
                else:
                    info_gui.right_active_duration = 0
        case "2_cars_left":
            if info_gui.one_car_duration >= 5 and info_gui.car1_data:
                if "Left" in info_gui.car1_data["active_aois"]:
                    new_state = "left_state"
                elif "Right" in info_gui.car1_data["active_aois"]:
                    new_state = "probable_pass"

    if new_state != info_gui.current_state:
        print(f"Frame {json_frame_number}: State transition from {info_gui.current_state} to {new_state}", file=sys.stderr)
    info_gui.current_state = new_state

    info_gui.update(num_cars, info_gui.car1_data, info_gui.car2_data, new_state)
    box_gui.update(cars, aoi_states)

    print(f"Frame {json_frame_number}: {num_cars} cars, State: {new_state}, Car1: {info_gui.car1_data}, Car2: {info_gui.car2_data}, AOI States: {aoi_states}, Total Passed: {info_gui.total_cars_passed}", file=sys.stderr)

    info_gui.root.after(20, process_frame, info_gui, box_gui)

def rectangles_overlap(box1, box2):
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    if x1 + w1 < x2 or x1 > x2 + w2 or y1 + h1 < y2 or y1 > y2 + h2:
        return 0.0
    x_left = max(x1, x2)
    x_right = min(x1 + w1, x2 + w2)
    y_top = max(y1, y2)
    y_bottom = min(y1 + h1, y2 + h2)
    overlap_area = (x_right - x_left) * (y_bottom - y_top)
    area1 = w1 * h1
    return overlap_area / area1 if area1 > 0 else 0.0

def main():
    info_root = tk.Tk()
    info_gui = InfoGUI(info_root)
    box_root = tk.Toplevel()
    box_gui = BoxGUI(box_root)
    info_root.after(20, process_frame, info_gui, box_gui)
    try:
        info_root.mainloop()
    except Exception as e:
        print(f"GUI error: {e}", file=sys.stderr)
    finally:
        info_gui.close()

if __name__ == "__main__":
    main()