from flask import Flask, request, jsonify
import threading
import os

app = Flask(__name__)

# Global variables for tracking car counts
entry_total_passed = 0
exit_total_passed = 0
current_cars = 0
lock = threading.Lock()

# Directory for count.txt
BASE_DIR = "/home/abraham/Estacionamiento_B"

def write_count_to_file(count):
    """Write the current car count to count.txt."""
    try:
        with open(os.path.join(BASE_DIR, "count.txt"), "w") as f:
            f.write(str(count))
    except Exception as e:
        print(f"Error writing to count.txt: {e}")

@app.route('/update_passed', methods=['POST'])
def update_passed():
    global entry_total_passed, exit_total_passed, current_cars
    try:
        data = request.get_json()
        if not data or "role" not in data or "total_cars_passed" not in data:
            return jsonify({"error": "Missing role or total_cars_passed"}), 400

        role = data["role"]
        total_cars_passed = data["total_cars_passed"]

        with lock:
            if role == "entry":
                entry_total_passed = total_cars_passed
            elif role == "exit":
                exit_total_passed = total_cars_passed
            else:
                return jsonify({"error": "Invalid role"}), 400

            # Calculate current cars
            new_current_cars = entry_total_passed - exit_total_passed
            if new_current_cars != current_cars:
                current_cars = new_current_cars
                write_count_to_file(current_cars)
                print(f"Current cars in parking lot: {current_cars}")

        return jsonify({"status": "success", "current_cars": current_cars}), 200
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Initialize count.txt with 0
    write_count_to_file(0)
    print(f"Current cars in parking lot: {current_cars}")
    app.run(host="0.0.0.0", port=5000, debug=False)