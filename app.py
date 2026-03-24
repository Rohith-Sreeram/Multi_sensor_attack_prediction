from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import csv
import io
import os
import time
import threading
import statistics

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ml-training-dashboard-secret'

# Read DATABASE_URL from environment for Render PostgreSQL
db_url = os.environ.get('DATABASE_URL', 'sqlite:///network_params.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ------------------------------------------------------------------
# Database Model
# ------------------------------------------------------------------
class NetworkParam(db.Model):
    __tablename__ = 'network_params'
    id            = db.Column(db.Integer, primary_key=True)
    byte_rate     = db.Column(db.Float, nullable=False)
    packet_rate   = db.Column(db.Float, nullable=False)
    packet_size_variance = db.Column(db.Float, nullable=False)
    time_gap_variance    = db.Column(db.Float, nullable=False)
    time_gap_mean        = db.Column(db.Float, nullable=False)
    packet_size_mean     = db.Column(db.Float, nullable=False)
    timestamp            = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id':                   self.id,
            'byte_rate':            self.byte_rate,
            'packet_rate':          self.packet_rate,
            'packet_size_variance': self.packet_size_variance,
            'time_gap_variance':    self.time_gap_variance,
            'time_gap_mean':        self.time_gap_mean,
            'packet_size_mean':     self.packet_size_mean,
            'timestamp':            self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        }


# In-memory capture state
capture_state = {
    'active':  False,
    'target':  0,
    'current': 0,
    'window_time': 2.0,
}

# Network packet tracking
recent_packets = []
packets_lock = threading.Lock()
last_db_insert_time = 0.0

# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


# ------------------------------------------------------------------
# Capture Session Management
# ------------------------------------------------------------------
@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.get_json()
    target = int(data.get('target', 0))
    window_time = float(data.get('window_time', 2.0))
    
    if target <= 0:
        return jsonify({'success': False, 'message': 'Target must be > 0'}), 400
    if window_time <= 0:
        return jsonify({'success': False, 'message': 'Window time must be > 0'}), 400

    capture_state['target']  = target
    capture_state['current'] = 0
    capture_state['active']  = True
    capture_state['window_time'] = window_time

    socketio.emit('session_update', {
        'active':  True,
        'target':  target,
        'current': 0,
        'window_time': window_time,
    })
    return jsonify({'success': True, 'target': target, 'window_time': window_time})


@app.route('/api/session/stop', methods=['POST'])
def stop_session():
    capture_state['active'] = False
    socketio.emit('session_update', {
        'active':  False,
        'target':  capture_state['target'],
        'current': capture_state['current'],
        'window_time': capture_state['window_time'],
    })
    return jsonify({'success': True})


@app.route('/api/session/restart', methods=['POST'])
def restart_session():
    """Reset the capture: stop session, clear DB records, reset counters."""
    capture_state['active']  = False
    capture_state['target']  = 0
    capture_state['current'] = 0

    # Clear all stored network parameter records
    NetworkParam.query.delete()
    db.session.commit()

    socketio.emit('session_restart', {})
    return jsonify({'success': True})


@app.route('/api/session/status', methods=['GET'])
def session_status():
    count = NetworkParam.query.count()
    return jsonify({
        'active':    capture_state['active'],
        'target':    capture_state['target'],
        'current':   capture_state['current'],
        'db_total':  count,
    })


# ------------------------------------------------------------------
# Network Parameters  (ESP32 / any source → POST here)
# ------------------------------------------------------------------
# Removed `/api/network` route. Metrics now computed internally in `/api/sensor`.


@app.route('/api/network/history', methods=['GET'])
def network_history():
    limit   = request.args.get('limit', 50, type=int)
    records = NetworkParam.query.order_by(NetworkParam.id.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in reversed(records)])


# ------------------------------------------------------------------
# Download captured data as CSV
# ------------------------------------------------------------------
@app.route('/api/download', methods=['GET'])
def download_csv():
    records = NetworkParam.query.order_by(NetworkParam.id.asc()).all()
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(['id', 'byte_rate', 'packet_rate',
                     'packet_size_variance', 'time_gap_variance',
                     'time_gap_mean', 'packet_size_mean', 'timestamp'])
    for r in records:
        ts_str = r.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        writer.writerow([r.id, r.byte_rate, r.packet_rate,
                         r.packet_size_variance, r.time_gap_variance,
                         r.time_gap_mean, r.packet_size_mean, ts_str])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='network_params.csv',
    )


# ------------------------------------------------------------------
# ESP32 Sensor Data  (Stored network metrics when active + relayed)
# ------------------------------------------------------------------
@app.route('/api/sensor', methods=['POST'])
def receive_sensor():
    global last_db_insert_time
    data = request.get_json()

    # relay to dashboard
    socketio.emit('sensor_data', data)

    # Calculate network packet metadata
    now = time.time()
    packet_size = request.content_length or len(str(data))
    
    with packets_lock:
        window_time = float(capture_state.get('window_time', 2.0))
        recent_packets.append((now, packet_size)) # Always add the current packet

        # NO: if the user wants non-overlapping "tumbling" windows that record at every interval:
        # 1. We keep appending.
        # 2. When (now - last_db_insert_time) >= window_time:
        #    - perform calculation
        #    - record to DB
        #    - set last_db_insert_time = now
        #    - CLEAR recent_packets so we start fresh for the next window
        
        if last_db_insert_time == 0:
            last_db_insert_time = now

        if now - last_db_insert_time >= window_time:
            if len(recent_packets) > 0:
                # ── USER'S DEFINED FORMULAS ──
                # mean packet size: sum of sizes / count
                sizes = [p[1] for p in recent_packets]
                times = [p[0] for p in recent_packets]
                
                packet_size_mean = statistics.mean(sizes)
                packet_size_variance = statistics.variance(sizes) if len(sizes) > 1 else 0.0
                
                # byte rate: total bytes / window_time
                byte_rate = sum(sizes) / window_time
                
                # packet rate: total packets / window_time
                packet_rate = len(sizes) / window_time
                
                # time gap mean: sum of gaps / (N - 1)
                if len(times) > 1:
                    gaps = [times[i] - times[i-1] for i in range(1, len(times))]
                    time_gap_mean = statistics.mean(gaps)
                    time_gap_variance = statistics.variance(gaps) if len(gaps) > 1 else 0.0
                else:
                    time_gap_mean = 0.0
                    time_gap_variance = 0.0
                
                last_db_insert_time = now
                
                network_data_dict = {
                    'byte_rate': byte_rate,
                    'packet_rate': packet_rate,
                    'packet_size_variance': packet_size_variance,
                    'time_gap_variance': time_gap_variance,
                    'time_gap_mean': time_gap_mean,
                    'packet_size_mean': packet_size_mean,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                }

                if capture_state['active']:
                    record = NetworkParam(
                        byte_rate=byte_rate,
                        packet_rate=packet_rate,
                        packet_size_variance=packet_size_variance,
                        time_gap_variance=time_gap_variance,
                        time_gap_mean=time_gap_mean,
                        packet_size_mean=packet_size_mean
                    )
                    db.session.add(record)
                    db.session.commit()
                    
                    network_data_dict['id'] = record.id
                    capture_state['current'] += 1

                socketio.emit('network_data', network_data_dict)

                # Tumbling window: Clear the list for the next chunk
                recent_packets.clear()

                if capture_state['active'] and capture_state['current'] >= capture_state['target']:
                    capture_state['active'] = False
                    socketio.emit('session_update', {
                        'active': False,
                        'target': capture_state['target'],
                        'current': capture_state['current'],
                        'message': 'Target reached – capture stopped automatically',
                    })
                    
    return jsonify({'success': True})


# ------------------------------------------------------------------
# Socket.IO events
# ------------------------------------------------------------------
@socketio.on('connect')
def on_connect():
    emit('session_update', {
        'active':  capture_state['active'],
        'target':  capture_state['target'],
        'current': capture_state['current'],
        'window_time': capture_state['window_time'],
    })


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
# Create tables if they don't exist
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
