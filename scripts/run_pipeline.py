import os
import sys
import json
import time
import re
import argparse
import pandas as pd
import pdfplumber
import sqlite3
import subprocess

from .utils import gemini_manager

# --- Configuration ---
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PDF_DIR = os.path.join(ROOT_DIR, 'data', 'raw_jee_materials')
DB_FILE = os.path.join(ROOT_DIR, 'data', 'question_bank.db')
CONFIG_FILE = os.path.join(ROOT_DIR, 'config', 'chapter_map.csv')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')


# ==============================================================================
# === DATABASE SETUP ===========================================================
# ==============================================================================

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    # The PRAGMA command is REMOVED from here.
    # It is now set permanently on the DB file during setup.
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("Existing database removed.", flush=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    print("Creating new database tables for augmentation pipeline...", flush=True)
    
    # Table creation remains the same
    cursor.execute('''
    CREATE TABLE parent_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT NOT NULL, options TEXT, answer TEXT,
        subject TEXT, chapter TEXT, source_file TEXT, source_page INTEGER
    );''')
    cursor.execute('''
    CREATE TABLE variant_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER,
        question_text TEXT NOT NULL, options TEXT, correct_answer TEXT,
        explanation TEXT, difficulty TEXT, diagram_latex TEXT,
        validation_status TEXT DEFAULT 'pending',
        FOREIGN KEY(parent_id) REFERENCES parent_questions(id)
    );''')
    cursor.execute('''
    CREATE TABLE processed_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL,
        page_num INTEGER NOT NULL, status TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_file, page_num)
    );''')
    
    # --- THE DEFINITIVE FIX ---
    # Set the journal mode to WAL permanently on the database file.
    # This only needs to be done ONCE during creation.
    cursor.execute("PRAGMA journal_mode=WAL;")
    print("Database journal mode permanently set to WAL for high concurrency.")
    
    conn.commit()
    conn.close()
    print("Database setup complete.", flush=True)

# ==============================================================================
# === CORE AUGMENTATION PIPELINE (No changes needed below this line) ===========
# ==============================================================================

def create_parser_prompt(page_text):
    return f"""
    You are a text analysis expert. Your task is to carefully read the following text from a textbook page and identify every distinct question.

    INSTRUCTIONS:
    1.  Look for numbered items (e.g., "1.", "2.", "Q1.", etc.).
    2.  Extract the full question text, including any context or diagrams described in text.
    3.  Extract all multiple-choice options (A, B, C, D, E) if they exist.
    4.  Extract the correct answer if it's provided immediately after the question or options.

    OUTPUT FORMAT:
    Your entire response MUST be a single, valid JSON formatted list `[]`. Each object in the list represents ONE question and must follow this exact schema:
    {{
      "question_text": "The full text of the question.",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": "The correct answer letter or text, if found."
    }}
    If no questions are found, return an empty list `[]`.

    TEXT TO PARSE:
    ---
    {page_text}
    ---
    """

def create_augment_prompt(parent_question, parent_options):
    options_str = "\n".join([f"- {opt}" for opt in parent_options]) if parent_options else "N/A"
    return f"""
    You are an expert curriculum developer specializing in creating high-quality assessment items for American high school AP exams.
    Your task is to take a single "parent" question and generate 6 new, distinct "variant" questions based on it.

    PARENT QUESTION:
    Text: "{parent_question}"
    Options: {options_str}

    INSTRUCTIONS:
    1.  **Generate 6 Variants:** Create two 'easy', two 'medium', and two 'hard' variants.
    2.  **CRITICAL FORMATTING RULES:**
        *   **Math and Symbols:** All chemical formulas, nuclides (e.g., `$^{{238}}_{{92}}$U`), variables (e.g., `$A_x$`), and equations MUST be enclosed in proper LaTeX math delimiters (`$...$`).
        *   **Options:** Do NOT include labels like 'A)', 'B)', etc., in the option text itself. The list should contain only the raw text for each option.
    3.  **Vary the Problem:**
        *   Easy: Simplify numbers, reduce steps, or ask for a direct definition.
        *   Medium: Use different numbers and a slightly different context.
        *   Hard: Introduce a complex scenario, require multiple steps, or combine concepts.
    4.  **Diagrams:**
        *   If a diagram is needed, you MUST generate valid LaTeX code using the `tikzpicture` environment.
        *   The code MUST be self-contained within a `\\begin{{tikzpicture}}...\\end{{tikzpicture}}` block.
        *   If no diagram is needed, the `diagram_latex` field MUST be an empty string `""`.
    5.  **Output Format:** Your response MUST be a single, valid JSON formatted list `[]` containing exactly 6 objects with this schema:
    {{
      "difficulty": "easy",
      "question_text": "The new variant question text with LaTeX math.",
      "options": ["New Option A text", "New Option B text", "New Option C text", "New Option D text"],
      "correct_answer": "The letter of the correct option (e.g., 'A').",
      "explanation": "A clear, step-by-step explanation with LaTeX math.",
      "diagram_latex": "\\begin{{tikzpicture}}...\\end{{tikzpicture}}"
    }}
    """

def run_augmentation_for_chapter(subject, pdf_file, chapter, start_page, end_page):
    conn = get_db_connection()
    cursor = conn.cursor()
    filepath = os.path.join(RAW_PDF_DIR, pdf_file)

    print(f"\n--- Starting augmentation for: {subject} - {chapter} ({pdf_file}) ---", flush=True)
    
    try:
        with pdfplumber.open(filepath) as pdf:
            for page_num in range(start_page, end_page + 1):
                cursor.execute("SELECT id FROM processed_log WHERE source_file = ? AND page_num = ?", (pdf_file, page_num))
                if cursor.fetchone():
                    print(f"  Page {page_num} already processed. Skipping.", flush=True)
                    continue
                
                print(f"  Processing Page {page_num}/{end_page}...", flush=True)
                page_text = pdf.pages[page_num - 1].extract_text()
                if not page_text or len(page_text.strip()) < 50:
                    cursor.execute("INSERT INTO processed_log (source_file, page_num, status) VALUES (?, ?, ?)", (pdf_file, page_num, 'skipped_no_text'))
                    conn.commit()
                    continue

                response_text = gemini_manager.get_response(create_parser_prompt(page_text))
                if not response_text:
                    cursor.execute("INSERT INTO processed_log (source_file, page_num, status) VALUES (?, ?, ?)", (pdf_file, page_num, 'failed_parsing'))
                    conn.commit()
                    continue

                try:
                    start = response_text.find('[')
                    end = response_text.rfind(']')
                    parent_questions = json.loads(response_text[start:end+1])
                except (json.JSONDecodeError, IndexError):
                    cursor.execute("INSERT INTO processed_log (source_file, page_num, status) VALUES (?, ?, ?)", (pdf_file, page_num, 'failed_json_decode'))
                    conn.commit()
                    continue
                
                if not parent_questions:
                    cursor.execute("INSERT INTO processed_log (source_file, page_num, status) VALUES (?, ?, ?)", (pdf_file, page_num, 'no_questions_found'))
                    conn.commit()
                    continue

                print(f"    --> Found {len(parent_questions)} parent questions on page {page_num}.", flush=True)

                for parent_q_idx, parent_q in enumerate(parent_questions):
                    print(f"      -> Augmenting parent question {parent_q_idx + 1}/{len(parent_questions)}...", flush=True)
                    
                    cursor.execute(
                        "INSERT INTO parent_questions (question_text, options, answer, subject, chapter, source_file, source_page) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (parent_q.get('question_text'), json.dumps(parent_q.get('options')), parent_q.get('answer'), subject, chapter, pdf_file, page_num)
                    )
                    parent_id = cursor.lastrowid

                    variant_response = gemini_manager.get_response(create_augment_prompt(parent_q.get('question_text'), parent_q.get('options')))
                    
                    if not variant_response:
                        print(f"        --> FAILED to generate variants for parent ID {parent_id}.", flush=True)
                        continue

                    try:
                        start_v = variant_response.find('[')
                        end_v = variant_response.rfind(']')
                        variants = json.loads(variant_response[start_v:end_v+1])
                        
                        for variant in variants:
                            cursor.execute(
                                "INSERT INTO variant_questions (parent_id, question_text, options, correct_answer, explanation, difficulty, diagram_latex) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (parent_id, variant.get('question_text'), json.dumps(variant.get('options')), variant.get('correct_answer'), variant.get('explanation'), variant.get('difficulty'), variant.get('diagram_latex'))
                            )
                        print(f"        --> Saved {len(variants)} variants for parent ID {parent_id}.", flush=True)
                    except (json.JSONDecodeError, IndexError):
                        print(f"        --> FAILED to decode JSON from augment response for parent ID {parent_id}.", flush=True)
                    
                    conn.commit()

                cursor.execute("INSERT INTO processed_log (source_file, page_num, status) VALUES (?, ?, ?)", (pdf_file, page_num, 'success'))
                conn.commit()

    except Exception as e:
        print(f"A critical error occurred during augmentation: {e}", flush=True)
    finally:
        print("\n--- Augmentation for chapter complete. ---", flush=True)
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Question Bank Augmentation Pipeline")
    parser.add_argument('--setup-db', action='store_true', help="Initialize a fresh database.")
    parser.add_argument('--augment', nargs='+', help="Run augmentation. Provide 'Subject' 'Chapter Name'")
    
    args = parser.parse_args()

    if args.setup_db:
        setup_database()
    elif args.augment:
        if len(args.augment) != 2:
            print("Error: --augment requires two arguments: 'Subject' 'Chapter Name'")
        else:
            subject, chapter = args.augment
            try:
                df = pd.read_csv(CONFIG_FILE)
                df.dropna(subset=['Start_Page', 'End_Page'], inplace=True)
                chapter_info = df[(df['Subject'] == subject) & (df['Chapter'] == chapter)]
                if chapter_info.empty:
                    print(f"Error: Chapter '{chapter}' for subject '{subject}' not found in {CONFIG_FILE}")
                else:
                    info = chapter_info.iloc[0]
                    run_augmentation_for_chapter(info['Subject'], info['PDF_File'], info['Chapter'], int(info['Start_Page']), int(info['End_Page']))
            except FileNotFoundError:
                print(f"Error: Configuration file not found at {CONFIG_FILE}")
    else:
        parser.print_help()