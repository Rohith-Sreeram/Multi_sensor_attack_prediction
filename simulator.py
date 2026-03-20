import time
import random
import requests
import argparse

def send_sensor_data(server_url, interval):
    while True:
        try:
            payload = {
                "accel": {
                    "x": random.uniform(-2.0, 2.0),
                    "y": random.uniform(-2.0, 2.0),
                    "z": random.uniform(-2.0, 2.0)
                },
                "gyro": {
                    "x": random.uniform(-250.0, 250.0),
                    "y": random.uniform(-250.0, 250.0),
                    "z": random.uniform(-250.0, 250.0)
                },
                "temperature": random.uniform(20.0, 35.0),
                "humidity": random.uniform(30.0, 70.0),
                "ir": {
                    "raw": random.randint(0, 4095),
                    "detected": random.choice([True, False])
                }
            }
            response = requests.post(f"{server_url}/api/sensor", json=payload, timeout=2)
            print(f"[SENSOR] Status: {response.status_code} | Payload: {payload['temperature']:.1f}°C, {payload['humidity']:.1f}%")
        except Exception as e:
            print(f"[SENSOR] Error: {e}")
        time.sleep(interval)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESP32 Hardware Simulator")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="Flask server URL (default: http://127.0.0.1:5000)")
    parser.add_argument("--sensor-interval", type=float, default=0.5, help="Sensor interval in seconds (default: 0.5)")
    args = parser.parse_args()

    print(f"Starting simulator...")
    print(f"Target URL: {args.url}")
    print(f"Sensor Interval: {args.sensor_interval}s\n")
    print("Press Ctrl+C to stop.")
    
    try:
        # Run directly in main thread since we only have one task now
        send_sensor_data(args.url, args.sensor_interval)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
