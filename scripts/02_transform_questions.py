import pandas as pd
import json
import time
from utils import get_db_connection, get_gemini_response

try:
    topic_df = pd.read_csv('config/topic_map.csv')
    print("Topic map loaded successfully.")
except FileNotFoundError:
    print("Error: config/topic_map.csv not found. Please ensure the file exists.")
    exit()

def get_target_format_from_topic(question_topic):
    if not question_topic:
        return "AP Style Question"
    
    match = topic_df[topic_df['JEE_Topic'].str.contains(question_topic, case=False, na=False)]
    
    if not match.empty:
        if pd.notna(match.iloc[0]['AP_Subject']) and pd.notna(match.iloc[0]['AP_Unit']):
            return f"{match.iloc[0]['AP_Subject']}: {match.iloc[0]['AP_Unit']}"
        elif pd.notna(match.iloc[0]['SAT_ACT_Category']):
            return f"{match.iloc[0]['SAT_ACT_Category']} Style Question"
            
    return "AP Style Question"

def transform_jee_question(question_data):
    original_question = question_data['question_text']
    original_options = json.loads(question_data['options']) if question_data['options'] else "N/A"
    question_topic = question_data['topic'] or 'Trigonometry'
    target_format = get_target_format_from_topic(question_topic)
    
    prompt = f"""
    You are an expert curriculum developer creating educational content for American standardized tests like the AP, SAT, and ACT.
    Your task is to transform the following Indian JEE (Joint Entrance Examination) question into a high-quality, {target_format} style question.

    **Original JEE Question:**
    - Subject/Topic: {question_topic}
    - Question: "{original_question}"
    - Options: {original_options}

    **Transformation Instructions:**
    1.  **Rephrase the Question:** Rewrite the question using the language, style, and tone commonly found on the target American exam. Add real-world context if it's an SAT/ACT style question. Keep it direct and conceptual for AP style.
    2.  **Modify Numerical Values:** If there are numbers, change them slightly to create a new, unique problem that tests the same core concept.
    3.  **Rewrite Options:** Generate a new set of four multiple-choice options (A, B, C, D) corresponding to the modified question. Ensure one is correct and the others are plausible distractors based on common mistakes.
    4.  **Provide Detailed Explanation:** Write a clear, step-by-step explanation for the correct answer, as would be expected in a high-quality test prep resource. Explain the 'why' behind the steps.
    5.  **Maintain Core Concept:** The new question MUST test the same fundamental scientific or mathematical principle as the original.

    **Output Format:**
    Provide the output in a single, clean JSON object with these exact keys: "generated_question", "generated_options" (a list of 4 strings), "correct_answer" (the letter, e.g., "C"), and "explanation".
    """
    
    print(f"  --> Transforming to {target_format} format...")
    response_text = get_gemini_response(prompt)
    
    if not response_text:
        return None

    try:
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1:
            json_str = response_text[start:end+1]
            return json.loads(json_str)
        return None
    except json.JSONDecodeError:
        print(f"  --> Failed to decode JSON from transformation response. Snippet: {response_text[:100]}")
        return None

def main():
    conn = get_db_connection()
    cursor = conn.cursor()

    while True:
        cursor.execute("SELECT * FROM jee_questions WHERE status = 'unprocessed' LIMIT 1")
        question_row = cursor.fetchone()

        if question_row is None:
            print("No more unprocessed questions found. Exiting.")
            break
        
        cursor.execute("SELECT COUNT(*) FROM jee_questions WHERE status = 'unprocessed'")
        remaining_count = cursor.fetchone()[0]

        print(f"\nProcessing question ID {question_row['id']} ({remaining_count} remaining)...")
        
        transformed_content = transform_jee_question(question_row)
        
        if transformed_content and all(k in transformed_content for k in ["generated_question", "generated_options", "correct_answer", "explanation"]):
            cursor.execute(
                "INSERT INTO generated_questions (original_jee_id, target_exam, question_text, options, correct_answer, explanation) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    question_row['id'],
                    get_target_format_from_topic(question_row['topic'] or 'Trigonometry'),
                    transformed_content.get('generated_question'),
                    json.dumps(transformed_content.get('generated_options')),
                    transformed_content.get('correct_answer'),
                    transformed_content.get('explanation')
                )
            )
            cursor.execute("UPDATE jee_questions SET status = 'transformed' WHERE id = ?", (question_row['id'],))
            conn.commit()
            print(f"  --> Successfully transformed and stored.")
        else:
            cursor.execute("UPDATE jee_questions SET status = 'failed_transform' WHERE id = ?", (question_row['id'],))
            conn.commit()
            print(f"  --> Failed to transform. Marked as failed.")

        time.sleep(1.2)

    conn.close()
    print("\n--- Transformation process complete. ---")

if __name__ == "__main__":
    main()