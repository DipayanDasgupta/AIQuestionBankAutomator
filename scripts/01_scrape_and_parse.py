import os
import pdfplumber
import json
import time
import re # NEW: Import regular expressions for cleaning
from utils import setup_database, get_db_connection, get_gemini_response

RAW_PDF_DIR = os.path.join('data', 'raw_jee_materials')

# NEW: Helper function to clean text before sending to the LLM
def clean_text(text):
    # Merge hyphenated words broken across lines
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    # Remove excessive newlines, keeping paragraph structure
    text = re.sub(r'\n\s*\n', '\n', text)
    # Remove page numbers or headers that might confuse the model
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
    return text

def parse_questions_from_text(text_chunk, source_file, page_num):
    # UPGRADED: A much more specific, few-shot prompt
    prompt = f"""
    You are an expert data extractor for educational content. Your task is to analyze the text from a single page of a JEE textbook and extract all multiple-choice questions.

    Look for headings like "Exercise for Session", "Example", or numbered lists. A question typically starts with a number (e.g., "1.", "Example 4.") and is followed by four or five options like "(a)", "(b)", "(c)", "(d)".

    **Example Input Text:**
    ---
    Exercise for Session 1
    1. The difference between two acute angles of a right angle triangle is 3π/10 rad. Find the angles in degree.
    ❙ Example 10. In the circle of 5 cm. radius, what is the length of the arc which subtends and angle of 33 15' at the centre.
    (a) 2.65 cm (b) 3.65 cm (c) 1.65 cm (d) none
    ---

    **Example JSON Output for the above text:**
    ```json
    [
      {{
        "question_text": "The difference between two acute angles of a right angle triangle is 3π/10 rad. Find the angles in degree.",
        "options": [],
        "answer": null
      }},
      {{
        "question_text": "In the circle of 5 cm. radius, what is the length of the arc which subtends and angle of 33 15' at the centre.",
        "options": ["2.65 cm", "3.65 cm", "1.65 cm", "none"],
        "answer": null
      }}
    ]
    ```

    **Instructions:**
    Return the result as a single, valid JSON formatted list. Each item in the list must be a distinct object with "question_text", "options", and "answer" keys.
    If no complete questions are found on the page, return an empty list `[]`.

    **Text to Analyze (from page {page_num} of {source_file}):**
    ---
    {text_chunk}
    ---
    """
    
    response_text = get_gemini_response(prompt)
    
    if not response_text:
        return []

    try:
        start = response_text.find('[')
        end = response_text.rfind(']')
        if start != -1 and end != -1:
            json_str = response_text[start:end+1]
            questions = json.loads(json_str)
            if isinstance(questions, dict): return [questions]
            return questions
        return []
    except json.JSONDecodeError:
        print(f"--> Failed to decode JSON for page {page_num}. Response snippet: {response_text[:100]}")
        return []

def main():
    setup_database()
    conn = get_db_connection()
    cursor = conn.cursor()
    total_questions_found = 0

    # ... (rest of the main function is the same as before)
    if not os.path.exists(RAW_PDF_DIR) or not os.listdir(RAW_PDF_DIR):
        print(f"Directory {RAW_PDF_DIR} is empty. Please add your PDF materials.")
        return

    for filename in os.listdir(RAW_PDF_DIR):
        if filename.lower().endswith('.pdf'):
            filepath = os.path.join(RAW_PDF_DIR, filename)
            print(f"\n--- Processing PDF: {filename} ---")
            
            try:
                with pdfplumber.open(filepath) as pdf:
                    num_pages = len(pdf.pages)
                    for i, page in enumerate(pdf.pages):
                        page_num = i + 1
                        print(f"  Processing Page {page_num} of {num_pages}...")
                        page_text = page.extract_text()

                        if not page_text or len(page_text.strip()) < 100:
                            print(f"    --> Skipping page {page_num} (not enough text).")
                            continue
                        
                        # NEW: Clean the text before sending it
                        cleaned_page_text = clean_text(page_text)

                        extracted_questions = parse_questions_from_text(cleaned_page_text, filename, page_num)
                        
                        if extracted_questions:
                            page_question_count = len(extracted_questions)
                            total_questions_found += page_question_count
                            print(f"    --> Found {page_question_count} questions.")
                            
                            for q in extracted_questions:
                                if q.get('question_text'):
                                    cursor.execute(
                                        "INSERT INTO jee_questions (question_text, options, answer, source_file, source_page, raw_text_chunk) VALUES (?, ?, ?, ?, ?, ?)",
                                        (q.get('question_text'), json.dumps(q.get('options')), q.get('answer'), filename, page_num, cleaned_page_text)
                                    )
                            conn.commit()
                        else:
                            print(f"    --> No questions found on this page.")
                        
                        print("    ...waiting 1.2 seconds...")
                        time.sleep(1.2)

            except Exception as e:
                print(f"An error occurred while processing {filename}: {e}")
                
    conn.close()
    print(f"\n--- All PDFs processed. Total questions found in this run: {total_questions_found} ---")

if __name__ == "__main__":
    main()