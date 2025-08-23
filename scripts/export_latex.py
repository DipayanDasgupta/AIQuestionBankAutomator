import os
import sqlite3
import json
import math
import re

# --- Configuration ---
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(ROOT_DIR, 'data', 'question_bank.db')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')

# --- Constants ---
QUESTIONS_PER_FILE = 50

# ==============================================================================
# === DATABASE CONNECTION ======================================================
# ==============================================================================

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ==============================================================================
# === LATEX DOCUMENT TEMPLATES =================================================
# ==============================================================================

def get_latex_preamble(title):
    """Returns the LaTeX header, now including the TikZ package for diagrams."""
    return r"""
\documentclass[12pt, letterpaper]{article}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{geometry}
\usepackage{tikz} % <-- ADDED FOR DIAGRAMS
\usetikzlibrary{shapes, arrows, positioning} % <-- Useful TikZ libraries
\geometry{a4paper, margin=1in}

\title{""" + title + r"""}
\author{AI Question Bank Automator}
\date{\today}

\begin{document}
\maketitle

\section*{Approved Questions}
\begin{enumerate}[label=\arabic*., itemsep=2em] % Increased item separation
"""

def get_latex_footer():
    """Returns the closing tags for a LaTeX document."""
    return r"""
\end{enumerate}
\end{document}
"""

# ==============================================================================
# === CORE EXPORT LOGIC ========================================================
# ==============================================================================

def clean_text(text):
    """A helper function to clean up common text issues for LaTeX."""
    if not text:
        return ""
    # Replace special characters that can break LaTeX
    text = text.replace('%', r'\%')
    text = text.replace('&', r'\&')
    text = text.replace('#', r'\#')
    return text

def format_question_as_latex(question_data):
    """Takes a database row and formats it into a professional LaTeX string."""
    
    question_text = clean_text(question_data['question_text'])
    explanation = clean_text(question_data['explanation'])
    
    # Safely load options from the JSON string
    try:
        options = json.loads(question_data['options']) if question_data['options'] else []
    except json.JSONDecodeError:
        options = []

    # Start with the question text
    latex_string = f"\\item {question_text}\n"
    
    # Add the diagram if it exists, wrapped in a centered figure
    if question_data['diagram_latex'] and 'tikzpicture' in question_data['diagram_latex']:
        latex_string += (
            "\\begin{center}\n"
            f"{question_data['diagram_latex']}\n"
            "\\end{center}\n"
        )
    
    # Add the multiple-choice options, cleaning them up
    if options:
        latex_string += "\\begin{enumerate}[label=(\\alph*), itemsep=0.5em]\n"
        for option in options:
            # Clean the option text and remove any leading "A) ", "B) ", etc.
            cleaned_option = clean_text(option)
            cleaned_option = re.sub(r'^[A-Ea-e][\)\.]\s*', '', cleaned_option)
            latex_string += f"    \\item {cleaned_option}\n"
        latex_string += "\\end{enumerate}\n"
        
    # Add a clear separator for the answer and explanation
    latex_string += "\\vspace{0.5em}\n"
    latex_string += f"\\textbf{{Answer:}} {question_data['correct_answer']}\\\\\n"
    latex_string += f"\\textbf{{Explanation:}} {explanation}\n"
    
    return latex_string

def export_approved_questions():
    """Fetches approved questions and writes them to batched LaTeX files."""
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("Fetching approved questions from the database...")
    
    query = """
    SELECT 
        vq.*,
        pq.subject,
        pq.chapter
    FROM 
        variant_questions vq
    JOIN 
        parent_questions pq ON vq.parent_id = pq.id
    WHERE 
        vq.validation_status = 'approved'
    ORDER BY
        pq.subject, pq.chapter, vq.id
    """
    
    cursor.execute(query)
    approved_questions = cursor.fetchall()
    conn.close()
    
    if not approved_questions:
        print("No approved questions found to export.")
        return

    print(f"Found {len(approved_questions)} approved questions. Preparing to write files...")

    total_files = math.ceil(len(approved_questions) / QUESTIONS_PER_FILE)
    
    for file_index in range(total_files):
        batch_number = file_index + 1
        start_index = file_index * QUESTIONS_PER_FILE
        end_index = start_index + QUESTIONS_PER_FILE
        question_batch = approved_questions[start_index:end_index]
        
        if not question_batch:
            continue
            
        # New, corrected line
        first_question_subject = question_batch[0]['subject'].replace(" ", "_").replace(":", "").replace("/", "_")
        filename = f"{first_question_subject}_Approved_Batch_{batch_number}.tex"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        print(f"Writing {len(question_batch)} questions to '{filepath}'...")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(get_latex_preamble(f"Approved Questions: Batch {batch_number}"))
            for question in question_batch:
                f.write(format_question_as_latex(question))
            f.write(get_latex_footer())
            
    print("\nExport complete!")
    print(f"All .tex files have been saved in the '{OUTPUT_DIR}' directory.")


if __name__ == "__main__":
    export_approved_questions()