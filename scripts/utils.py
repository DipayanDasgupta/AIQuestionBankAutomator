import os
import time
import google.generativeai as genai
from dotenv import load_dotenv
import sqlite3

class GeminiAPI:
    """A class to manage multiple API keys and rotate them."""
    def __init__(self):
        load_dotenv()
        self.keys = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 5) if os.getenv(f"GEMINI_API_KEY_{i}")]
        if not self.keys:
            raise ValueError("No GEMINI_API_KEY found in .env file. Please check your configuration.")
        self.current_key_index = 0
        print(f"Loaded {len(self.keys)} Gemini API keys.")

    def get_response(self, prompt_text):
        max_retries_per_key = 2
        for _ in range(len(self.keys) * max_retries_per_key):
            try:
                key = self.keys[self.current_key_index]
                self.current_key_index = (self.current_key_index + 1) % len(self.keys) # Rotate to next key for the next call

                genai.configure(api_key=key)
                safety_settings = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
                model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)
                
                response = model.generate_content(prompt_text)
                if not response.parts:
                    print(f"    --> Response blocked by API (Key Index: {self.current_key_index-1}). Skipping.")
                    return None
                return response.text

            except Exception as e:
                error_str = str(e)
                print(f"    --> API Error with Key Index {self.current_key_index-1}: {error_str[:50]}...")
                if "429" in error_str or "500" in error_str or "504" in error_str:
                    print("    --> Rotating key and waiting 5 seconds...")
                    time.sleep(5) # Shorter wait since we are rotating keys
                    continue
                else:
                    return None # Non-retriable error
        
        print("    --> All API keys failed after multiple retries. Skipping chunk.")
        return None

# Initialize a single API manager for the whole pipeline
gemini_manager = GeminiAPI()

# --- Database Functions (No changes here, but this is the final version) ---
DB_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'question_bank.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    if not os.path.exists(DB_FILE):
        print("Creating new database and tables...")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE jee_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, question_text TEXT NOT NULL, options TEXT, answer TEXT,
            subject TEXT, topic TEXT, source_file TEXT, source_page INTEGER, raw_text_chunk TEXT,
            status TEXT DEFAULT 'unprocessed'
        );''')
        cursor.execute('''
        CREATE TABLE generated_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, original_jee_id INTEGER, target_exam TEXT,
            question_text TEXT NOT NULL, options TEXT, correct_answer TEXT, explanation TEXT,
            validation_status TEXT DEFAULT 'pending', embedding BLOB,
            FOREIGN KEY(original_jee_id) REFERENCES jee_questions(id)
        );''')
        conn.commit()
        conn.close()
        print("Database setup complete.")