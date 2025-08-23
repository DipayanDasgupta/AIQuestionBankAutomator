import os
import sqlite3
import sys
import signal
import time

# --- Path Setup ---
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.export_latex import export_approved_questions

# --- Configuration ---
DB_FILE = os.path.join(ROOT_DIR, 'data', 'question_bank.db')
PID_FILE = os.path.join(ROOT_DIR, 'process.pid') # Path to the process lock file


def stop_running_pipeline():
    """Checks for a PID file and stops the running pipeline if it exists."""
    if os.path.exists(PID_FILE):
        print("Detected a running augmentation pipeline...")
        try:
            with open(PID_FILE, 'r') as f:
                pgid = int(f.read().strip())
            
            print(f"Stopping process group with PGID: {pgid}...")
            os.killpg(pgid, signal.SIGTERM)
            
            # Wait a moment for the process to terminate
            time.sleep(2)
            
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE) # Clean up if stop was slow
            
            print("Pipeline stopped successfully.")
            return True
        except (ValueError, ProcessLookupError, FileNotFoundError) as e:
            print(f"Could not stop the process, it may have already ended. Error: {e}")
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE) # Clean up stale file
            return True
    else:
        print("No running augmentation pipeline detected.")
        return False


def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, timeout=15)
    return conn

def approve_all_pending_questions():
    """Updates all 'pending' questions to 'approved'."""
    print("Connecting to the database for approval...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM variant_questions WHERE validation_status = 'pending'")
    count = cursor.fetchone()[0]

    if count == 0:
        print("No pending questions found to approve.")
        conn.close()
        return 0

    print(f"Found {count} pending questions. Updating their status to 'approved'...")
    
    try:
        cursor.execute("UPDATE variant_questions SET validation_status = 'approved' WHERE validation_status = 'pending'")
        conn.commit()
        updated_count = cursor.rowcount
        print(f"Successfully approved {updated_count} questions.")
        return updated_count
    except sqlite3.Error as e:
        print(f"A database error occurred during approval: {e}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    print("--- Emergency Auto-Approval and Export Script ---")
    
    was_running = stop_running_pipeline()
    
    # Step 1: Run the auto-validation
    approve_all_pending_questions()
    
    # Step 2: Run the LaTeX export
    print("\n--------------------------------------------------\n")
    print("Starting LaTeX export process for all approved questions...")
    export_approved_questions()

    print("\n--- Script finished. ---")
    if was_running:
        print("\nIMPORTANT: The background augmentation pipeline was stopped.")
        print("Please restart it from the web dashboard if you wish to continue generating questions.")