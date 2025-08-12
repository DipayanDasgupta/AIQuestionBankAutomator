# In scripts/05_generate_pdf.py

import json
from utils import get_db_connection
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

def generate_final_pdf():
    """
    Generates a PDF document from all 'approved' questions in the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    print("Fetching all approved questions from the database...")
    cursor.execute("SELECT * FROM generated_questions WHERE validation_status = 'approved' ORDER BY target_exam, id")
    questions = cursor.fetchall()
    
    conn.close()

    if not questions:
        print("No approved questions found. Nothing to generate.")
        return

    output_filename = os.path.join('output', 'Final_Question_Bank.pdf')
    doc = SimpleDocTemplate(output_filename)
    styles = getSampleStyleSheet()
    story = []
    
    current_exam_group = ""
    question_counter = 1

    print(f"Found {len(questions)} approved questions. Starting PDF generation...")

    for q in questions:
        exam_group = q['target_exam'] or "General Questions"

        # Add a title for a new group of questions
        if exam_group != current_exam_group:
            if current_exam_group != "": # Add a page break between sections
                story.append(PageBreak())
            story.append(Paragraph(exam_group, styles['h1']))
            story.append(Spacer(1, 0.2*inch))
            current_exam_group = exam_group
            question_counter = 1 # Reset counter for new section
        
        # Format the question
        story.append(Paragraph(f"{question_counter}. {q['question_text']}", styles['Normal']))
        story.append(Spacer(1, 0.1*inch))
        
        # Format the options
        try:
            options = json.loads(q['options'])
            for i, opt in enumerate(options):
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{chr(65+i)}) {opt}", styles['Normal']))
        except:
            story.append(Paragraph("&nbsp;&nbsp;&nbsp;&nbsp;Error: Options not available.", styles['Italic']))

        story.append(Spacer(1, 0.2*inch))
        question_counter += 1

    # --- Create an Answer Key Section at the end ---
    story.append(PageBreak())
    story.append(Paragraph("Answer Key and Explanations", styles['h1']))
    story.append(Spacer(1, 0.2*inch))
    
    question_counter = 1
    current_exam_group = ""

    for q in questions:
        exam_group = q['target_exam'] or "General Questions"
        if exam_group != current_exam_group:
            story.append(Spacer(1, 0.2*inch))
            story.append(Paragraph(exam_group, styles['h2']))
            current_exam_group = exam_group
            question_counter = 1

        story.append(Paragraph(f"<b>{question_counter}. Correct Answer: {q['correct_answer']}</b>", styles['Normal']))
        story.append(Paragraph(f"<i>Explanation:</i> {q['explanation']}", styles['Normal']))
        story.append(Spacer(1, 0.2*inch))
        question_counter += 1

    # Build the PDF
    doc.build(story)
    print(f"\nSuccessfully generated PDF: '{output_filename}'")

if __name__ == "__main__":
    generate_final_pdf()