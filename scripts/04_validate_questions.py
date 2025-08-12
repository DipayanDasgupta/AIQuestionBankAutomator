# In scripts/04_validate_questions.py

import json
from utils import get_db_connection

def manual_validator():
    """
    An interactive tool to manually approve or reject generated questions.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    while True:
        # Fetch one question that is pending validation
        cursor.execute("SELECT * FROM generated_questions WHERE validation_status = 'pending' LIMIT 1")
        question = cursor.fetchone()

        if not question:
            print("\nNo more questions are pending validation. Great work!")
            break

        # Fetch the original JEE question for context
        original_question = None
        if question['original_jee_id']:
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
        except:
            print("  Options could not be parsed.")
        
        print(f"\nCorrect Answer: {question['correct_answer']}")
        print(f"\nExplanation:\n{question['explanation']}")
        print("\n" + "-"*80)

        # Get user input
        action = input("Enter your action: (a)pprove, (r)eject, (s)kip, (q)uit -> ").lower()

        if action == 'a':
            cursor.execute("UPDATE generated_questions SET validation_status = 'approved' WHERE id = ?", (question['id'],))
            conn.commit()
            print("  --> Status set to 'approved'.")
        elif action == 'r':
            cursor.execute("UPDATE generated_questions SET validation_status = 'rejected' WHERE id = ?", (question['id'],))
            conn.commit()
            print("  --> Status set to 'rejected'.")
        elif action == 's':
            print("  --> Skipping this question for now.")
            continue
        elif action == 'q':
            print("Quitting validation session.")
            break
        else:
            print("  --> Invalid input. Please try again.")

    conn.close()

if __name__ == "__main__":
    manual_validator()