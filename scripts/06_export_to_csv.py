import sqlite3
import pandas as pd
import os
import json
import re

# Define the path to your database and the desired output directory
DB_FILE = os.path.join('data', 'question_bank.db')
OUTPUT_DIR = 'output'

def clean_text(text):
    """A helper function to clean up text fields for better readability."""
    if not isinstance(text, str):
        return text
    # Replace multiple newlines with a single space
    text = re.sub(r'\s*\n\s*', ' ', text)
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def preprocess_and_export():
    """
    Connects to the SQLite database, pre-processes the data for readability,
    and exports both tables to well-structured CSV files.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file not found at '{DB_FILE}'")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        print(f"Successfully connected to the database at '{DB_FILE}'.")

        # --- Process and Export jee_questions Table ---
        print("\nProcessing table: 'jee_questions'...")
        df_jee = pd.read_sql_query("SELECT * FROM jee_questions", conn)

        if not df_jee.empty:
            # Clean text fields
            df_jee['question_text'] = df_jee['question_text'].apply(clean_text)
            
            # Reorder columns for better readability
            jee_cols_order = ['id', 'status', 'source_file', 'source_page', 'subject', 'topic', 
                              'question_text', 'options', 'answer', 'raw_text_chunk']
            # Ensure all expected columns exist before reordering
            df_jee = df_jee.reindex(columns=[col for col in jee_cols_order if col in df_jee.columns])

            csv_path = os.path.join(OUTPUT_DIR, 'processed_jee_questions.csv')
            df_jee.to_csv(csv_path, index=False)
            print(f"  --> Successfully exported {len(df_jee)} rows to '{csv_path}'")
        else:
            print("  --> Table 'jee_questions' is empty.")

        # --- Process and Export generated_questions Table ---
        print("\nProcessing table: 'generated_questions'...")
        df_gen = pd.read_sql_query("SELECT * FROM generated_questions", conn)

        if not df_gen.empty:
            # Expand the 'options' JSON into separate columns
            options_expanded = df_gen['options'].apply(lambda x: json.loads(x) if x else [])
            df_options = pd.DataFrame(options_expanded.tolist(), index=df_gen.index).add_prefix('Option_')

            # Join the new option columns back to the main dataframe
            df_gen = pd.concat([df_gen, df_options], axis=1)
            
            # Clean the main text fields
            df_gen['question_text'] = df_gen['question_text'].apply(clean_text)
            df_gen['explanation'] = df_gen['explanation'].apply(clean_text)
            
            # Reorder columns and drop the original JSON 'options' column
            gen_cols_order = [
                'id', 'original_jee_id', 'target_exam', 'validation_status', 'question_text', 
                'correct_answer', 'Option_0', 'Option_1', 'Option_2', 'Option_3', 'explanation'
            ]
            # Rename Option columns for clarity (Option_0 -> Option_A, etc.)
            rename_dict = {f'Option_{i}': f'Option_{chr(65+i)}' for i in range(len(df_options.columns))}
            df_gen.rename(columns=rename_dict, inplace=True)
            
            final_cols = [rename_dict.get(col, col) for col in gen_cols_order if col in df_gen.columns or col in rename_dict]
            
            df_gen = df_gen.reindex(columns=final_cols)

            csv_path = os.path.join(OUTPUT_DIR, 'processed_generated_questions.csv')
            df_gen.to_csv(csv_path, index=False)
            print(f"  --> Successfully exported {len(df_gen)} rows to '{csv_path}'")
        else:
            print("  --> Table 'generated_questions' is empty.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            print("\nDatabase connection closed.")

if __name__ == "__main__":
    preprocess_and_export()
    print("Export process finished.")