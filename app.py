import os
import sys
import json
import sqlite3
import subprocess
import signal
import time
from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd

# --- Correctly configure project paths ---
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.run_pipeline import setup_database

# --- Configuration ---
CONFIG_FILE = os.path.join(ROOT_DIR, 'config', 'chapter_map.csv')
DB_FILE = os.path.join(ROOT_DIR, 'data', 'question_bank.db')
LOG_FILE = os.path.join(ROOT_DIR, 'process.log')
# --- NEW: Lock file to track the running process ---
PID_FILE = os.path.join(ROOT_DIR, 'process.pid')

# --- App Initialization ---
app = Flask(__name__)

# --- Global state for managing the background process ---
process_handle = None

# --- Custom Template Filter ---
@app.template_filter('fromjson')
def fromjson_filter(value):
    if value is None:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

# --- Database Connection ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

# --- Routes ---
@app.route('/')
def dashboard():
    chapters = []
    try:
        df = pd.read_csv(CONFIG_FILE)
        df.dropna(subset=['Start_Page', 'End_Page'], inplace=True)
        df['Start_Page'] = df['Start_Page'].astype(int)
        df['End_Page'] = df['End_Page'].astype(int)
        chapters = df.to_dict('records')
    except Exception as e:
        print(f"Could not load chapters: {e}")
    
    stats = get_current_stats()
    return render_template('index.html', chapters=chapters, stats=stats)


@app.route('/get_stats')
def get_stats():
    stats = get_current_stats()
    return jsonify(stats)

def get_current_stats():
    stats = { "total_parents": 0, "total_variants": 0, "pending_validation": 0, "approved": 0 }
    if os.path.exists(DB_FILE):
        try:
            conn = get_db_connection()
            stats["total_parents"] = conn.execute('SELECT COUNT(*) FROM parent_questions').fetchone()[0]
            stats["total_variants"] = conn.execute('SELECT COUNT(*) FROM variant_questions').fetchone()[0]
            stats["pending_validation"] = conn.execute("SELECT COUNT(*) FROM variant_questions WHERE validation_status = 'pending'").fetchone()[0]
            stats["approved"] = conn.execute("SELECT COUNT(*) FROM variant_questions WHERE validation_status = 'approved'").fetchone()[0]
            conn.close()
        except Exception as e:
            print(f"Could not query DB stats: {e}")
    return stats

@app.route('/start-augmentation', methods=['POST'])
def start_augmentation():
    global process_handle
    if process_handle and process_handle.poll() is None or os.path.exists(PID_FILE):
        return jsonify({"status": "error", "message": "A process is already running."})

    chapter_selection = request.form.get('chapter')
    subject, chapter_name = chapter_selection.split('|', 1)

    with open(LOG_FILE, 'w') as f:
        f.write(f"Starting augmentation for: {subject} - {chapter_name}\n")

    command = [sys.executable, '-m', 'scripts.run_pipeline', '--augment', subject, chapter_name]
    log_handle = open(LOG_FILE, 'a')
    process_handle = subprocess.Popen(command, stdout=log_handle, stderr=log_handle, text=True, preexec_fn=os.setsid)
    
    # --- NEW: Create the PID file ---
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpgid(process_handle.pid)))
    
    return jsonify({"status": "success", "message": f"Started augmentation for {chapter_name}."})

@app.route('/stop-process', methods=['POST'])
def stop_process():
    global process_handle
    if process_handle and process_handle.poll() is None:
        os.killpg(os.getpgid(process_handle.pid), signal.SIGTERM)
        process_handle.wait()
        process_handle = None
    # Also clean up the PID file if it exists, regardless of the handle
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    with open(LOG_FILE, 'a') as f:
        f.write("\n\n--- PROCESS MANUALLY TERMINATED BY USER ---\n")
    return jsonify({"status": "success", "message": "Process terminated."})


@app.route('/status')
def status():
    # The running status is now determined by the existence of the PID file for robustness
    is_running = os.path.exists(PID_FILE)
    
    log_content = "Log file not found."
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            log_content = f.read()

    return jsonify({"running": is_running, "output": log_content})
    
@app.route('/setup-database', methods=['POST'])
def setup_db_route():
    try:
        # Stop any running process before resetting the DB
        if os.path.exists(PID_FILE):
            stop_process()
        setup_database()
        return jsonify({"status": "success", "message": "Database has been successfully reset."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/validate')
def validate():
    # This function should be a read-only operation and is safe.
    try:
        conn = get_db_connection()
        variant = conn.execute("SELECT * FROM variant_questions WHERE validation_status = 'pending' LIMIT 1").fetchone()
        parent = None
        if variant:
            parent = conn.execute("SELECT * FROM parent_questions WHERE id = ?", (variant['parent_id'],)).fetchone()
        conn.close()
        return render_template('validate.html', variant=variant, parent=parent)
    except sqlite3.OperationalError as e:
         return f"Database is currently locked by the background process. Please wait a moment and refresh. Error: {e}", 503


@app.route('/submit-validation', methods=['POST'])
def submit_validation():
    question_id = request.form.get('question_id')
    action = request.form.get('action')
    
    if action in ['approved', 'rejected']:
        try:
            conn = get_db_connection()
            conn.execute("UPDATE variant_questions SET validation_status = ? WHERE id = ?", (action, question_id))
            conn.commit()
            conn.close()
            print(f"Validation for ID {question_id} successful.")
        except sqlite3.OperationalError as e:
            print(f"A database error occurred during validation: {e}")
            return "Error: A database error occurred. The background process may be writing. Please try again.", 500

    return redirect(url_for('validate'))

def main():
    if not os.path.exists(DB_FILE):
        print("Database not found. Initializing a new one...")
        setup_database()
    
    # Clean up any stale PID file on startup
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

if __name__ == '__main__':
    main()