#!/bin/bash

# Color codes for better terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}--- Starting AI Question Bank Automator Setup ---${NC}"

# --- 1. Initialize Git Repository ---
echo -e "\n${YELLOW}Step 1: Initializing Git repository...${NC}"
git init
git remote add origin https://github.com/DipayanDasgupta/AIQuestionBankAutomator.git
echo -e "${GREEN}Git repository initialized and remote 'origin' added.${NC}"

# --- 2. Create Project Directory Structure ---
echo -e "\n${YELLOW}Step 2: Creating project directory structure...${NC}"
mkdir -p data/raw_jee_materials data/processed scripts output config
echo "Created directories: data/, scripts/, output/, config/"

# --- 3. Create .gitignore file ---
echo -e "\n${YELLOW}Step 3: Creating .gitignore file...${NC}"
cat <<EOL > .gitignore
# Python
venv/
__pycache__/
*.pyc

# Environment variables
.env

# Data & Output Files (these can get large, consider Git LFS if you must track)
data/
output/
*.pdf
*.csv

# IDE specific
.vscode/
.idea/
EOL
echo -e "${GREEN}.gitignore created to exclude venv, .env, data, and output files.${NC}"

# --- 4. Set up Python Virtual Environment ---
echo -e "\n${YELLOW}Step 4: Setting up Python virtual environment 'venv'...${NC}"
python3 -m venv venv
source venv/bin/activate
echo -e "${GREEN}Virtual environment created and activated.${NC}"

# --- 5. Install Required Python Libraries ---
echo -e "\n${YELLOW}Step 5: Upgrading pip and installing required libraries...${NC}"
pip install --upgrade pip
pip install pypdf2 pdfplumber beautifulsoup4 scrapy pandas reportlab sentence-transformers "google-cloud-aiplatform" python-dotenv
echo -e "${GREEN}All required Python libraries have been installed.${NC}"

# Create a requirements.txt file for reproducibility
pip freeze > requirements.txt
echo -e "${GREEN}requirements.txt file created.${NC}"

# --- 6. Create Placeholder for API Key ---
echo -e "\n${YELLOW}Step 6: Creating secure .env file for API keys...${NC}"
cat <<EOL > .env
# Store your secret keys here. This file is ignored by Git.
GEMINI_API_KEY='YOUR_API_KEY_HERE'
GOOGLE_CLOUD_PROJECT='YOUR_PROJECT_ID_HERE'
EOL
echo -e "${GREEN}.env file created. ${YELLOW}IMPORTANT: Edit this file with your actual keys and DO NOT commit it to Git.${NC}"

# --- 7. Create Placeholder Python Scripts ---
echo -e "\n${YELLOW}Step 7: Creating placeholder Python scripts...${NC}"
touch scripts/01_scrape_and_parse.py
touch scripts/02_transform_questions.py
touch scripts/03_check_duplicates.py
touch scripts/04_validate_questions.py
touch scripts/05_generate_pdf.py
touch scripts/utils.py
touch config/topic_map.csv
echo "Created placeholder scripts in the 'scripts/' directory and a topic map in 'config/'."

# --- 8. Make Initial Git Commit ---
echo -e "\n${YELLOW}Step 8: Making the first Git commit...${NC}"
git add .
git commit -m "Initial project setup: directory structure, venv, and dependencies"
echo -e "${GREEN}Initial commit created. You are ready to push to GitHub with 'git push -u origin main' (or master).${NC}"

echo -e "\n${GREEN}--- Setup Complete! ---${NC}"
echo "Your environment is ready. You can now start adding your JEE materials to 'data/raw_jee_materials' and begin coding in the 'scripts/' directory."
