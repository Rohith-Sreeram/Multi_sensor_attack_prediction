from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import csv
import io
import os

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
    timestamp            = db.Column(db.DateTime, default=datetime.utcnow)

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
}

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
    if target <= 0:
        return jsonify({'success': False, 'message': 'Target must be > 0'}), 400

    capture_state['target']  = target
    capture_state['current'] = 0
    capture_state['active']  = True

    socketio.emit('session_update', {
        'active':  True,
        'target':  target,
        'current': 0,
    })
    return jsonify({'success': True, 'target': target})


@app.route('/api/session/stop', methods=['POST'])
def stop_session():
    capture_state['active'] = False
    socketio.emit('session_update', {
        'active':  False,
        'target':  capture_state['target'],
        'current': capture_state['current'],
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
@app.route('/api/network', methods=['POST'])
def receive_network():
    if not capture_state['active']:
        return jsonify({'success': False, 'message': 'No active capture session'}), 400

    if capture_state['current'] >= capture_state['target']:
        capture_state['active'] = False
        socketio.emit('session_update', {
            'active':  False,
            'target':  capture_state['target'],
            'current': capture_state['current'],
            'message': 'Target reached – capture stopped',
        })
        return jsonify({'success': False, 'message': 'Target reached'}), 400

    data = request.get_json()
    try:
        record = NetworkParam(
            byte_rate            = float(data['byte_rate']),
            packet_rate          = float(data['packet_rate']),
            packet_size_variance = float(data['packet_size_variance']),
            time_gap_variance    = float(data['time_gap_variance']),
            time_gap_mean        = float(data['time_gap_mean']),
            packet_size_mean     = float(data['packet_size_mean']),
        )
        db.session.add(record)
        db.session.commit()

        capture_state['current'] += 1

        if capture_state['current'] >= capture_state['target']:
            capture_state['active'] = False
            socketio.emit('session_update', {
                'active':  False,
                'target':  capture_state['target'],
                'current': capture_state['current'],
                'message': 'Target reached – capture stopped automatically',
            })

        # Broadcast the new record to all connected clients
        socketio.emit('network_data', record.to_dict())

        return jsonify({
            'success': True,
            'saved':   capture_state['current'],
            'target':  capture_state['target'],
        })

    except (KeyError, ValueError) as e:
        return jsonify({'success': False, 'message': f'Bad data: {e}'}), 400


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
        writer.writerow([r.id, r.byte_rate, r.packet_rate,
                         r.packet_size_variance, r.time_gap_variance,
                         r.time_gap_mean, r.packet_size_mean, r.timestamp])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='network_params.csv',
    )


# ------------------------------------------------------------------
# ESP32 Sensor Data  (NOT stored – only relayed via Socket.IO)
# ------------------------------------------------------------------
@app.route('/api/sensor', methods=['POST'])
def receive_sensor():
    data = request.get_json()
    # relay to dashboard – nothing written to DB
    socketio.emit('sensor_data', data)
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
    })


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
# Create tables if they don't exist
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
