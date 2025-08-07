import json
from utils import get_db_connection, get_gemini_response

def transform_jee_question(question_data, target_format="AP Physics 1"):
    """
    Uses Gemini to transform a single JEE question into the target format.
    """
    original_question = question_data['question_text']
    original_options = json.loads(question_data['options'])

    prompt = f"""
    You are an expert in creating educational content for American standardized tests.
    Your task is to transform the following Indian JEE question into a {target_format} style question.

    **Original JEE Question:**
    - Question: "{original_question}"
    - Options: {original_options}

    **Transformation Instructions:**
    1.  **Rephrase the Question:** Rewrite the question using the language and style of {target_format}. Add real-world context if appropriate for an AP/SAT question.
    2.  **Modify Numerical Values:** If there are numbers, change them slightly to create a new problem that tests the same concept.
    3.  **Rewrite Options:** Generate a new set of four multiple-choice options (A, B, C, D) corresponding to the modified question. Ensure one is correct and the others are plausible distractors.
    4.  **Provide Detailed Explanation:** Write a clear, step-by-step explanation for the correct answer.
    5.  **Maintain Core Concept:** The new question must test the same fundamental principle as the original.

    **Output Format:**
    Provide the output in a single, clean JSON object with these exact keys: "generated_question", "generated_options" (a list of 4 strings), "correct_answer" (the letter, e.g., "C"), and "explanation".
    """

    print(f"Transforming question ID {question_data['id']} to {target_format} format...")
    response_text = get_gemini_response(prompt)
    
    if not response_text:
        return None

    cleaned_response = response_text.strip().replace('```json', '').replace('```', '').strip()

    try:
        transformed_data = json.loads(cleaned_response)
        return transformed_data
    except json.JSONDecodeError:
        print("Failed to decode JSON from transformation response.")
        print("Response received:", cleaned_response)
        return None

def main():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all unprocessed JEE questions
    cursor.execute("SELECT * FROM jee_questions WHERE status = 'unprocessed'")
    unprocessed_questions = cursor.fetchall()
    
    print(f"Found {len(unprocessed_questions)} unprocessed questions to transform.")

    for question_row in unprocessed_questions:
        # TODO: Use the topic_map.csv to determine the target_format dynamically
        # For now, we'll hardcode the target format for testing
        target_exam_format = "AP Physics 1" 
        
        transformed_content = transform_jee_question(question_row, target_exam_format)
        
        if transformed_content:
            # Insert the new question into the generated_questions table
            cursor.execute(
                "INSERT INTO generated_questions (original_jee_id, target_exam, question_text, options, correct_answer, explanation) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    question_row['id'],
                    target_exam_format,
                    transformed_content.get('generated_question'),
                    json.dumps(transformed_content.get('generated_options')),
                    transformed_content.get('correct_answer'),
                    transformed_content.get('explanation')
                )
            )
            
            # Update the status of the original question
            cursor.execute("UPDATE jee_questions SET status = 'transformed' WHERE id = ?", (question_row['id'],))
            conn.commit()
            print(f"Successfully transformed and stored question ID {question_row['id']}.")
        else:
            # Mark as failed to avoid retrying every time
            cursor.execute("UPDATE jee_questions SET status = 'failed' WHERE id = ?", (question_row['id'],))
            conn.commit()
            print(f"Failed to transform question ID {question_row['id']}.")

    conn.close()
    print("\n--- Transformation process complete. ---")

if __name__ == "__main__":
    main()