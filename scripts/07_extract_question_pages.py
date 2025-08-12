import os
import time
import PyPDF2
import pdfplumber
from utils import get_gemini_response
import argparse

# --- Main Functions ---
def is_page_a_question_page(page_text):
    """
    Uses the Gemini API to determine if a page primarily contains questions.
    Returns True if it's a question page, False otherwise.
    """
    if not page_text or len(page_text.strip()) < 100:
        return False

    prompt = f"""
    Analyze the following text from a single textbook page.
    Does this page primarily contain practice questions, exercises, or solved examples?
    Answer with a single word: YES or NO.

    Text to analyze:
    ---
    {page_text[:2000]}
    ---
    """
    # We only send the first 2000 characters to save tokens and speed up the check
    
    response = get_gemini_response(prompt)
    
    if response and "YES" in response.upper():
        return True
    return False

def extract_pages_to_new_pdf(input_pdf_path, output_pdf_path, pages_to_include):
    """
    Creates a new PDF containing only the specified page numbers from the input PDF.
    """
    try:
        pdf_writer = PyPDF2.PdfWriter()
        pdf_reader = PyPDF2.PdfReader(input_pdf_path)

        for page_num in pages_to_include:
            # Page numbers in PyPDF2 are 0-indexed
            if 0 <= page_num - 1 < len(pdf_reader.pages):
                page = pdf_reader.pages[page_num - 1]
                pdf_writer.add_page(page)

        with open(output_pdf_path, 'wb') as out_file:
            pdf_writer.write(out_file)
        
        print(f"\nSuccessfully created new PDF with {len(pages_to_include)} pages at '{output_pdf_path}'")

    except Exception as e:
        print(f"\nAn error occurred while creating the PDF: {e}")

def main(input_filename):
    """
    Main script to identify question pages and generate a new PDF.
    """
    input_pdf_path = os.path.join('data', input_filename)
    output_dir = 'output'
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(input_pdf_path):
        print(f"Error: The file '{input_filename}' was not found in the 'data' folder.")
        return

    question_page_numbers = []
    
    try:
        with pdfplumber.open(input_pdf_path) as pdf:
            num_pages = len(pdf.pages)
            print(f"--- Analyzing '{input_filename}' ({num_pages} pages) ---")
            
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                print(f"  Checking page {page_num}/{num_pages}...")
                page_text = page.extract_text()

                if is_page_a_question_page(page_text):
                    print(f"    --> Found questions on page {page_num}.")
                    question_page_numbers.append(page_num)
                else:
                    print(f"    --> Not a question page.")
                
                time.sleep(1.2) # Respect API rate limits

        if question_page_numbers:
            output_filename = f"{os.path.splitext(input_filename)[0]}_questions_only.pdf"
            output_pdf_path = os.path.join(output_dir, output_filename)
            extract_pages_to_new_pdf(input_pdf_path, output_pdf_path, question_page_numbers)
        else:
            print("\nNo pages with questions were identified in this document.")

    except Exception as e:
        print(f"An error occurred while processing the PDF: {e}")

if __name__ == "__main__":
    # --- How to use this script ---
    # In your terminal, run it like this:
    # python scripts/07_extract_question_pages.py "Arihant Trigonometry.pdf"
    
    parser = argparse.ArgumentParser(description="Extract pages with questions from a PDF.")
    parser.add_argument("filename", type=str, help="The name of the PDF file in the 'data' folder.")
    args = parser.parse_args()
    
    main(args.filename)