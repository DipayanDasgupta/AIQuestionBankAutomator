#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

echo "--- Starting Project Restructuring ---"

# 1. Clean up unnecessary files and directories
echo "Step 1: Cleaning up old/unnecessary files..."
# Remove the old JEE PDFs as the new focus is on augmenting from AP PDFs
rm -f data/raw_jee_materials/NARAYANA*.pdf
# Remove system-generated files if they exist
rm -f data/raw_jee_materials/*:Zone.Identifier
# Remove the old 'processed' directory as it's no longer used
rm -rf data/processed
echo "Cleanup complete."

# 2. Create the new directory for web templates
echo "Step 2: Creating 'templates' directory..."
mkdir -p templates
echo "Directory 'templates' created."

# 3. Rename the old config file and create the new one
echo "Step 3: Archiving old topic_map.csv and creating new chapter_map.csv..."
mv config/topic_map.csv config/topic_map.csv.bak
touch config/chapter_map.csv

# Pre-populate the new chapter_map.csv with headers to guide the user
echo "Subject,PDF_File,Chapter,Start_Page,End_Page" > config/chapter_map.csv
echo "# --- Add your chapter mappings here ---" >> config/chapter_map.csv
echo "New 'config/chapter_map.csv' created. Please populate it with your book's chapter data."

# 4. Create the new empty files for the web app
echo "Step 4: Creating new files for the Flask application..."
touch app.py
touch templates/layout.html
touch templates/index.html
touch templates/validate.html
touch .env

# Pre-populate the .env file with the required structure
echo "# Google Gemini API Keys (at least one is required)" > .env
echo "GEMINI_API_KEY_1=\"YOUR_FIRST_API_KEY_HERE\"" >> .env
echo "GEMINI_API_KEY_2=\"\"" >> .env
echo "GEMINI_API_KEY_3=\"\"" >> .env
echo "GEMINI_API_KEY_4=\"\"" >> .env
echo "New '.env' file created. Please add your API keys."

# 5. Optional: Clean up the old setup script
read -p "Do you want to remove the old setup_pipeline.sh file? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    rm -f setup_pipeline.sh
    echo "Removed setup_pipeline.sh."
fi

echo "--- Restructuring Complete! ---"
echo ""
echo "NEXT STEPS:"
echo "1. Populate 'config/chapter_map.csv' with your PDF chapter info."
echo "2. Add your Google Gemini API keys to the '.env' file."
echo "3. Replace the contents of 'scripts/run_pipeline.py' and 'scripts/utils.py' with the new code."
echo "4. Copy the new HTML and Python code into 'app.py' and the files in the 'templates/' directory."
echo "5. Run 'pip install flask pandas' to install the new dependencies."
echo "6. Run 'python scripts/run_pipeline.py --setup-db' to initialize the new database."
echo "7. Run 'flask --app app run' to start the web UI."