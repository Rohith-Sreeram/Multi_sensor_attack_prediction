import time
import random
import requests
import argparse

def send_sensor_data(server_url, interval):
    # Strip any trailing slashes to prevent 308 redirects
    server_url = server_url.rstrip("/")
    
    # Use a persistent session to keep the TCP/TLS connection alive
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    
    while True:
        try:
            t = random.uniform(20.0, 35.0)
            h = random.uniform(30.0, 70.0)
            ir_det = random.choice([True, False])
            u_dist = random.uniform(5.0, 200.0)
            v_val = random.uniform(0.0, 10.0)

            payload = {
                "temperature": t,
                "humidity": h,
                "ir": {
                    "detected": ir_det
                },
                "ultrasonic": {
                    "distance": u_dist
                },
                "vibration": {
                    "value": v_val
                }
            }
            # Increased timeout to 30s to allow free Render instances to wake up from sleep
            response = session.post(f"{server_url}/api/sensor", json=payload, timeout=30)
            print(f"[SENSOR] Status: {response.status_code} | T:{t:.1f}°C H:{h:.1f}% IR:{ir_det} U:{u_dist:.1f}cm V:{v_val:.1f}")
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
