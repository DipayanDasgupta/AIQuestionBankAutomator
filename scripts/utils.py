import sqlite3
import os
import time
import google.generativeai as genai
from dotenv import load_dotenv

# --- Database Functions ---
DB_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'question_bank.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    db_dir = os.path.dirname(DB_FILE)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    if os.path.exists(DB_FILE):
        print("Database file already exists. Assuming schema is correct.")
        return

    print("Creating new database and tables...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE jee_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT NOT NULL,
        options TEXT,
        answer TEXT,
        subject TEXT,
        topic TEXT,
        source_file TEXT,
        source_page INTEGER, -- The correct schema
        raw_text_chunk TEXT,
        status TEXT DEFAULT 'unprocessed'
    );
    ''')
    cursor.execute('''
    CREATE TABLE generated_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_jee_id INTEGER,
        target_exam VARCHAR(10),
        question_text TEXT NOT NULL,
        options TEXT,
        correct_answer TEXT,
        explanation TEXT,
        validation_status TEXT DEFAULT 'pending',
        embedding BLOB,
        FOREIGN KEY(original_jee_id) REFERENCES jee_questions(id)
    );
    ''')
    conn.commit()
    conn.close()
    print("Database setup complete.")

# --- Gemini API Functions ---
# In scripts/utils.py

def get_gemini_response(prompt_text):
    """
    Sends a prompt to the Gemini API with relaxed safety settings and robust retry logic.
    """
    load_dotenv()
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key or api_key == 'YOUR_API_KEY_HERE':
        raise ValueError("GEMINI_API_KEY not found or not set in .env file.")

    genai.configure(api_key=api_key)

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt_text)
            
            # Check for empty response parts before accessing .text
            if not response.parts:
                reason = "Unknown"
                try:
                    # Try to get the specific block reason if available
                    reason = response.prompt_feedback.block_reason
                except Exception:
                    pass # Ignore error if block_reason is not available
                print(f"    --> Response was blocked by API (Reason: {reason}). Skipping page.")
                return None
                
            return response.text
            
        except Exception as e:
            error_str = str(e)
            # UPGRADED: Now retries on both rate limits and server errors
            if "429" in error_str or "500" in error_str:
                wait_time = 60 + attempt * 15 # Increase wait time on subsequent failures
                print(f"    --> API Error ({error_str[:20]}). Waiting {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"    --> An unexpected, non-retriable API error occurred: {e}")
                return None
    
    print("    --> Exceeded max retries for API call. Skipping chunk.")
    return None