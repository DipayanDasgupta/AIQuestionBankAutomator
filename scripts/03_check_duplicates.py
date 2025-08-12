# In scripts/03_check_duplicates.py

import sqlite3
from sentence_transformers import SentenceTransformer, util
from utils import get_db_connection

def find_and_flag_duplicates():
    """
    Finds semantically similar questions in the generated_questions table
    and flags them as duplicates.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all approved or pending questions that haven't been checked
    print("Fetching generated questions to check for duplicates...")
    cursor.execute("SELECT id, question_text FROM generated_questions WHERE validation_status IN ('pending', 'approved')")
    questions = cursor.fetchall()

    if len(questions) < 2:
        print("Not enough questions to compare. Exiting.")
        conn.close()
        return

    print(f"Found {len(questions)} questions to analyze.")
    
    # Extract IDs and texts for processing
    ids = [q['id'] for q in questions]
    texts = [q['question_text'] for q in questions]

    # Load a pre-trained sentence embedding model
    print("Loading sentence embedding model (this may take a moment)...")
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Generate embeddings for all question texts
    print("Generating embeddings for all questions...")
    embeddings = model.encode(texts, convert_to_tensor=True, show_progress_bar=True)

    # Use the model's paraphrase mining utility to find similar pairs
    # This is much more efficient than comparing every pair manually
    print("Searching for similar question pairs...")
    similar_pairs = util.paraphrase_mining(embeddings, top_k=2, score_threshold=0.95)

    duplicate_ids_to_flag = set()

    if not similar_pairs:
        print("No potential duplicates found with the current threshold (0.95).")
    else:
        print(f"\nFound {len(similar_pairs)} potential duplicate pairs:")
        for score, i, j in similar_pairs:
            id1, text1 = ids[i], texts[i]
            id2, text2 = ids[j], texts[j]
            
            print(f"  - Score: {score:.2f}")
            print(f"    Q ID {id1}: {text1}")
            print(f"    Q ID {id2}: {text2}\n")
            
            # Add the ID of the second question in the pair to the set to be flagged
            # We keep the one with the lower ID by default
            duplicate_ids_to_flag.add(id2)

    if duplicate_ids_to_flag:
        print(f"Flagging {len(duplicate_ids_to_flag)} questions as 'rejected_duplicate'...")
        for dupe_id in duplicate_ids_to_flag:
            cursor.execute("UPDATE generated_questions SET validation_status = 'rejected_duplicate' WHERE id = ?", (dupe_id,))
        conn.commit()
        print("Database updated.")
    
    conn.close()
    print("\nDuplicate check process finished.")

if __name__ == "__main__":
    find_and_flag_duplicates()