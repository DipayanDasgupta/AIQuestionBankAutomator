# ==============================================================================
# AI Question Bank Automator - Full End-to-End Pipeline
# ==============================================================================

# --- Core Imports ---
import os
import json
import time
import re
import argparse
import pandas as pd
import pdfplumber
import sqlite3
import subprocess
import google.generativeai as genai
from dotenv import load_dotenv

# --- Library-specific Imports ---
try:
    from sentence_transformers import SentenceTransformer, util
except ImportError:
    print("Warning: 'sentence-transformers' not found. --check-duplicates will not work. Run 'pip install sentence-transformers'.")
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
except ImportError:
    print("Warning: 'reportlab' not found. --generate-pdf will not work. Run 'pip install reportlab'.")

# --- Configuration ---
RAW_PDF_DIR = os.path.join('data', 'raw_jee_materials')
OUTPUT_DIR = 'output'
DB_FILE = os.path.join('data', 'question_bank.db')

# ==============================================================================
# === UTILITY SECTION (API and Database Management) ============================
# ==============================================================================

class GeminiAPI:
    """Manages multiple API keys, rotates them, and handles retries."""
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
                self.current_key_index = (self.current_key_index + 1) % len(self.keys)

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
                    time.sleep(5)
                    continue
                else:
                    return None
        
        print("    --> All API keys failed after multiple retries. Skipping chunk.")
        return None

gemini_manager = GeminiAPI()

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

# ==============================================================================
# === MODE 1: GENERATION PIPELINE (Parse -> Classify -> Transform) =============
# ==============================================================================

def create_end_to_end_prompt(text_chunk, topic_list_str, source_file, page_num):
    """Creates a single, powerful prompt to handle parsing, classification, and transformation."""
    return f"""
    You are an expert curriculum developer. Your task is to perform a full analysis of a single page from a JEE textbook.
    
    TASK (3 steps):
    1.  **Parse:** Identify all distinct questions on the page.
    2.  **Classify:** For each question found, classify its topic by choosing the BEST match from the "Available Topics" list below.
    3.  **Transform:** For each classified question, transform it into a high-quality AP/SAT/ACT style question suitable for American high school students. This involves rephrasing, changing numerical values, creating new options (A,B,C,D), and writing a clear explanation.

    Available Topics:
    {topic_list_str}

    CRITICAL OUTPUT FORMAT:
    Your entire response MUST be a single, valid JSON formatted list `[]`. Each object in the list represents ONE processed question and must follow this exact schema:
    {{
      "original_question": "The question text as parsed from the source.",
      "original_options": ["Option A", "Option B", ...],
      "classified_topic": "The single best topic from the provided list.",
      "transformed_question": "The new, rephrased AP/SAT/ACT style question.",
      "transformed_options": ["New Option A", "New Option B", "New Option C", "New Option D"],
      "correct_answer": "The letter of the correct new option (e.g., 'C').",
      "explanation": "The detailed step-by-step explanation for the new question."
    }}
    If no questions are found on the page, return an empty list `[]`.

    Text to Analyze (from page {page_num} of {source_file}):
    ---
    {text_chunk}
    ---
    """

def run_generation_pipeline():
    """The main end-to-end, resumable pipeline for generating questions."""
    setup_database()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        topic_df = pd.read_csv('config/topic_map.csv')
        valid_topics = topic_df[~topic_df['JEE_Topic'].str.startswith('#', na=True)]['JEE_Topic'].tolist()
        topic_list_str = "\n".join(f"- {topic}" for topic in valid_topics)
    except FileNotFoundError:
        print("FATAL: config/topic_map.csv not found. Exiting.")
        return

    all_pdfs = [f for f in os.listdir(RAW_PDF_DIR) if f.lower().endswith('.pdf')]
    print(f"Found {len(all_pdfs)} PDF files to process.")

    for filename in all_pdfs:
        filepath = os.path.join(RAW_PDF_DIR, filename)
        try:
            with pdfplumber.open(filepath) as pdf:
                num_pages = len(pdf.pages)
                cursor.execute("SELECT MAX(source_page) FROM jee_questions WHERE source_file = ?", (filename,))
                last_processed_page = (cursor.fetchone() or [0])[0] or 0
                
                if last_processed_page >= num_pages:
                    print(f"\n--- PDF '{filename}' is already fully processed. Skipping. ---")
                    continue
                
                print(f"\n--- Processing PDF: {filename} (Resuming from page {last_processed_page + 1}) ---")

                for i in range(last_processed_page, num_pages):
                    page_num = i + 1
                    print(f"  Processing Page {page_num}/{num_pages}...")
                    page_text = pdf.pages[i].extract_text()

                    if not page_text or len(page_text.strip()) < 150:
                        print("    --> Skipping page (not enough text).")
                        continue
                    
                    prompt = create_end_to_end_prompt(page_text, topic_list_str, filename, page_num)
                    response_text = gemini_manager.get_response(prompt)
                    
                    if not response_text:
                        print("    --> No valid response from API. Moving to next page.")
                        time.sleep(1)
                        continue

                    try:
                        start = response_text.find('[')
                        end = response_text.rfind(']')
                        if start != -1 and end != -1:
                            processed_questions = json.loads(response_text[start:end+1])
                            if processed_questions:
                                print(f"    --> Found and processed {len(processed_questions)} questions.")
                                for q_data in processed_questions:
                                    cursor.execute(
                                        "INSERT INTO jee_questions (question_text, options, topic, source_file, source_page, status) VALUES (?, ?, ?, ?, ?, ?)",
                                        (q_data.get('original_question'), json.dumps(q_data.get('original_options')), q_data.get('classified_topic'), filename, page_num, 'transformed')
                                    )
                                    original_id = cursor.lastrowid
                                    cursor.execute(
                                        "INSERT INTO generated_questions (original_jee_id, question_text, options, correct_answer, explanation) VALUES (?, ?, ?, ?, ?)",
                                        (original_id, q_data.get('transformed_question'), json.dumps(q_data.get('transformed_options')), q_data.get('correct_answer'), q_data.get('explanation'))
                                    )
                                conn.commit()
                        else:
                            print("    --> No questions found on this page.")
                    except json.JSONDecodeError:
                        print(f"    --> Failed to decode JSON from LLM response.")
                    time.sleep(0.5)
        except Exception as e:
            print(f"An error occurred while processing {filename}: {e}")
    conn.close()
    print("\n--- End-to-end generation pipeline run complete. ---")

# ==============================================================================
# === MODE 2: DUPLICATE CHECKING ===============================================
# ==============================================================================

def find_and_flag_duplicates():
    """
    Finds semantically similar questions using semantic_search and flags them for review.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    print("Fetching generated questions to check for duplicates...")
    cursor.execute("SELECT id, question_text FROM generated_questions WHERE validation_status IN ('pending', 'approved')")
    questions = cursor.fetchall()

    if len(questions) < 2:
        print("Not enough questions to compare. Exiting.")
        conn.close()
        return

    ids = [q['id'] for q in questions]
    texts = [q['question_text'] for q in questions]
    print(f"Loading sentence embedding model for {len(texts)} questions...")
    # You can use 'all-mpnet-base-v2' for higher accuracy if needed, but 'all-MiniLM-L6-v2' is faster.
    model = SentenceTransformer('all-MiniLM-L6-v2') 
    embeddings = model.encode(texts, convert_to_tensor=True, show_progress_bar=True)
    
    print("Searching for similar question pairs using semantic search...")
    # Find the top 2 matches for each question against the entire set.
    # The first match for each will be the question itself.
    similar_pairs_search = util.semantic_search(embeddings, embeddings, top_k=2)

    duplicate_ids_to_flag = set()
    threshold = 0.95

    # Iterate through the results. `i` is the index of the query question.
    for i, pairs in enumerate(similar_pairs_search):
        # The first pair (pairs[0]) is the question itself (score=1.0).
        # We are interested in the second pair (pairs[1]), which is the nearest neighbor.
        if len(pairs) > 1:
            closest_match = pairs[1]
            score = closest_match['score']
            j = closest_match['corpus_id'] # This is the index of the similar question in the list

            # To avoid processing the same pair twice (e.g., A-B and B-A),
            # we only consider pairs where the current index `i` is less than the found index `j`.
            if i < j and score >= threshold:
                id1 = ids[i]
                id2 = ids[j]
                
                print(f"  - Score: {score:.2f} | Found potential duplicate:")
                print(f"    Q ID {id1}: {texts[i]}")
                print(f"    Q ID {id2}: {texts[j]}\n")

                # Add the one with the higher ID to be flagged as a duplicate
                duplicate_ids_to_flag.add(id2)
    
    if duplicate_ids_to_flag:
        print(f"Flagging {len(duplicate_ids_to_flag)} questions as 'rejected_duplicate'...")
        for dupe_id in duplicate_ids_to_flag:
            cursor.execute("UPDATE generated_questions SET validation_status = 'rejected_duplicate' WHERE id = ?", (dupe_id,))
        conn.commit()
    else:
        print("No duplicates found with the current threshold.")
        
    conn.close()
    print("\nDuplicate check process finished.")

# ==============================================================================
# === MODE 3: MANUAL VALIDATION ================================================
# ==============================================================================

def manual_validator():
    """An interactive tool to manually approve or reject generated questions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    while True:
        cursor.execute("SELECT * FROM generated_questions WHERE validation_status = 'pending' LIMIT 1")
        question = cursor.fetchone()
        if not question:
            print("\nNo more questions are pending validation. Great work!")
            break
        
        cursor.execute("SELECT * FROM jee_questions WHERE id = ?", (question['original_jee_id'],))
        original_question = cursor.fetchone()

        print("\n" + "="*80)
        print(f"Validating Question ID: {question['id']} (from JEE ID: {question['original_jee_id']})")
        print("="*80)
        if original_question:
            print(f"\n--- ORIGINAL JEE QUESTION ---\n{original_question['question_text']}\n")

        print("--- GENERATED QUESTION ---")
        print(f"Q: {question['question_text']}")
        try:
            options = json.loads(question['options'])
            for i, opt in enumerate(options):
                print(f"  {chr(65+i)}) {opt}")
        except: pass
        
        print(f"\nCorrect Answer: {question['correct_answer']}")
        print(f"\nExplanation:\n{question['explanation']}")
        print("\n" + "-"*80)

        action = input("Enter your action: (a)pprove, (r)eject, (s)kip, (q)uit -> ").lower()
        if action == 'a':
            cursor.execute("UPDATE generated_questions SET validation_status = 'approved' WHERE id = ?", (question['id'],))
            print("  --> Status set to 'approved'.")
        elif action == 'r':
            cursor.execute("UPDATE generated_questions SET validation_status = 'rejected' WHERE id = ?", (question['id'],))
            print("  --> Status set to 'rejected'.")
        elif action == 's':
            print("  --> Skipping.")
            continue
        elif action == 'q':
            break
        else:
            print("  --> Invalid input.")
        conn.commit()
    conn.close()

# ==============================================================================
# === MODE 4: PDF & CSV EXPORT =================================================
# ==============================================================================

def generate_final_pdf():
    """Generates a PDF document from all 'approved' questions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_questions WHERE validation_status = 'approved' ORDER BY target_exam, id")
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        print("No approved questions found. Nothing to generate.")
        return

    output_filename = os.path.join(OUTPUT_DIR, 'Final_Question_Bank.pdf')
    doc = SimpleDocTemplate(output_filename)
    styles = getSampleStyleSheet()
    story = []
    
    # Question Section
    story.append(Paragraph("Generated Question Bank", styles['h1']))
    for i, q in enumerate(questions):
        story.append(Spacer(1, 0.2*inch))
        story.append(Paragraph(f"{i+1}. {q['question_text']}", styles['Normal']))
        try:
            options = json.loads(q['options'])
            for j, opt in enumerate(options):
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{chr(65+j)}) {opt}", styles['Normal']))
        except: pass
    
    # Answer Key Section
    story.append(PageBreak())
    story.append(Paragraph("Answer Key and Explanations", styles['h1']))
    for i, q in enumerate(questions):
        story.append(Spacer(1, 0.2*inch))
        story.append(Paragraph(f"<b>{i+1}. Correct Answer: {q['correct_answer']}</b>", styles['Normal']))
        story.append(Paragraph(f"<i>Explanation:</i> {q['explanation']}", styles['Normal']))

    doc.build(story)
    print(f"\nSuccessfully generated PDF: '{output_filename}'")

def preprocess_and_export_csv():
    """Exports database tables to clean, human-readable CSV files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = get_db_connection()
    
    # Export jee_questions
    df_jee = pd.read_sql_query("SELECT * FROM jee_questions", conn)
    if not df_jee.empty:
        csv_path = os.path.join(OUTPUT_DIR, 'processed_jee_questions.csv')
        df_jee.to_csv(csv_path, index=False)
        print(f"Successfully exported {len(df_jee)} rows to '{csv_path}'")

    # Export generated_questions with expanded options
    df_gen = pd.read_sql_query("SELECT * FROM generated_questions", conn)
    if not df_gen.empty:
        options_expanded = df_gen['options'].apply(lambda x: json.loads(x) if x and x.startswith('[') else [])
        df_options = pd.DataFrame(options_expanded.tolist(), index=df_gen.index).add_prefix('Option_')
        df_gen = pd.concat([df_gen.drop('options', axis=1), df_options], axis=1)
        csv_path = os.path.join(OUTPUT_DIR, 'processed_generated_questions.csv')
        df_gen.to_csv(csv_path, index=False)
        print(f"Successfully exported {len(df_gen)} rows to '{csv_path}'")
        
    conn.close()

# ==============================================================================
# === MODE 4 (UPGRADED): LaTeX PDF Generation with Batching & Smart Sanitizing =
# ==============================================================================

def sanitize_text_chunk(text):
    """Aggressively escapes special LaTeX characters in a plain text string."""
    if not isinstance(text, str): return str(text)
    replacements = {
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
        '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
        '\\': r'\textbackslash{}'
    }
    regex = re.compile('|'.join(re.escape(key) for key in replacements.keys()))
    return regex.sub(lambda match: replacements[match.group(0)], text)

def smart_latex_escape(text):
    """
    Splits text into math and text segments. Escapes only the text segments.
    This is the key to fixing the formatting issues.
    """
    if not isinstance(text, str): return str(text)
    # Split the text by LaTeX math delimiters ($...$ or $$...$$)
    # The parentheses in the regex keep the delimiters in the resulting list.
    parts = re.split(r'(\$\$?.*?\$\$?)', text)
    escaped_parts = []
    for part in parts:
        # If the part is a math delimiter block, leave it as is.
        if part.startswith('$') and part.endswith('$'):
            escaped_parts.append(part)
        # Otherwise, it's plain text and must be sanitized.
        else:
            escaped_parts.append(sanitize_text_chunk(part))
    return "".join(escaped_parts)

def generate_latex_pdf():
    """Generates high-quality, batched PDF documents from all 'approved' questions."""
    # Check for LaTeX installation first
    if subprocess.run(['which', 'pdflatex'], capture_output=True).returncode != 0:
        print("\nERROR: pdflatex command not found.")
        print("Please install a LaTeX distribution. On Debian/Ubuntu (WSL), run: sudo apt-get install texlive-full")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_questions WHERE validation_status = 'approved' ORDER BY id")
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        print("No approved questions found. Run the validator first (--validate).")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    BATCH_SIZE = 50
    num_batches = (len(questions) + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Found {len(questions)} approved questions. This will be split into {num_batches} PDF files.")

    for i in range(num_batches):
        start_index = i * BATCH_SIZE
        end_index = start_index + BATCH_SIZE
        current_batch = questions[start_index:end_index]
        batch_num = i + 1

        print(f"\n--- Generating Batch {batch_num} of {num_batches} ---")

        latex_preamble = r"""
\documentclass[12pt]{article}
\usepackage[a4paper, margin=1in]{geometry}
\usepackage{amsmath, amssymb, amsfonts}
\usepackage{enumitem}
\usepackage{hyperref}
\linespread{1.3}
\begin{document}
"""
        latex_postamble = r"\end{document}"
        
        question_body = f"\\section*{{Generated Question Bank - Part {batch_num}}}"
        answer_body = f"\\newpage\n\\section*{{Answer Key and Explanations - Part {batch_num}}}"

        for q_index, q_data in enumerate(current_batch):
            global_q_num = start_index + q_index + 1
            
            # Use the new smart escaping function
            question_text = smart_latex_escape(q_data['question_text'])
            
            options = []
            try:
                raw_options = json.loads(q_data['options'])
                for opt in raw_options:
                    cleaned_opt = re.sub(r'^[A-Z][\).] \s*', '', opt)
                    options.append(smart_latex_escape(cleaned_opt))
            except:
                options = ["Error parsing options."]

            correct_answer = sanitize_text_chunk(q_data['correct_answer'])
            explanation = smart_latex_escape(q_data['explanation'])

            # Build question block for this question
            question_body += f"\n\n\\subsection*{{Question {global_q_num}}}\n{question_text}\n"
            question_body += "\\begin{enumerate}[label=\\Alph*)]\n"
            for opt in options:
                question_body += f"    \\item {opt}\n"
            question_body += "\\end{enumerate}"

            # Build answer block for this question
            answer_body += f"\n\n\\subsection*{{Question {global_q_num}}}\n"
            answer_body += f"\\textbf{{Correct Answer: {correct_answer}}}\n\n"
            answer_body += f"\\textbf{{Explanation:}} {explanation}"

        full_latex_doc = latex_preamble + question_body + answer_body + latex_postamble
        
        # --- Write and Compile each batch ---
        tex_filename = f"Final_Question_Bank_Part_{batch_num}"
        tex_filepath = os.path.join(OUTPUT_DIR, f"{tex_filename}.tex")
        pdf_filepath = os.path.join(OUTPUT_DIR, f"{tex_filename}.pdf")

        with open(tex_filepath, 'w', encoding='utf-8') as f:
            f.write(full_latex_doc)
        
        print(f"  LaTeX file written to '{tex_filepath}'. Compiling to PDF...")

        for _ in range(2): # Compile twice for references
            process = subprocess.run(
                ['pdflatex', '-interaction=nonstopmode', '-output-directory', OUTPUT_DIR, tex_filepath],
                capture_output=True, text=True, check=False
            )
        
        if process.returncode == 0:
            print(f"  --> Successfully generated PDF: '{pdf_filepath}'")
        else:
            print(f"  --> LaTeX Compilation Error for batch {batch_num}. Check '{tex_filename}.log' in the output folder for details.")
        
        # Clean up auxiliary files
        for ext in ['.aux', '.log']:
            try: os.remove(os.path.join(OUTPUT_DIR, f"{tex_filename}{ext}"))
            except OSError: pass

# ==============================================================================
# === MAIN EXECUTION ROUTER ====================================================
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Question Bank Automator Pipeline", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--generate', action='store_true', help="Run the full end-to-end generation pipeline.")
    parser.add_argument('--check-duplicates', action='store_true', help="Find and flag duplicate questions in the database.")
    parser.add_argument('--validate', action='store_true', help="Start the interactive manual validation tool.")
    parser.add_argument('--generate-pdf', action='store_true', help="Generate a final PDF from all approved questions using ReportLab.")
    parser.add_argument('--generate-latex-pdf', action='store_true', help="Generate a final, high-quality PDF from all approved questions using LaTeX.")
    parser.add_argument('--export-csv', action='store_true', help="Export database tables to processed CSV files.")

    args = parser.parse_args()

    if args.generate:
        run_generation_pipeline()
    elif args.check_duplicates:
        find_and_flag_duplicates()
    elif args.validate:
        manual_validator()
    elif args.generate_pdf:
        generate_final_pdf()
    elif args.generate_latex_pdf:
        generate_latex_pdf()
    elif args.export_csv:
        preprocess_and_export_csv()
    else:
        print("No action specified. Please use one of the available commands:")
        print("  --generate          : Run the full generation pipeline.")
        print("  --check-duplicates  : Flag duplicate questions.")
        print("  --validate          : Start the manual validation tool.")
        print("  --generate-pdf      : Create the final PDF of approved questions using ReportLab.")
        print("  --generate-latex-pdf: Create the final PDF of approved questions using LaTeX.")
        print("  --export-csv        : Create processed CSV files for review.")
        print("\nExample: python scripts/run_pipeline.py --generate")