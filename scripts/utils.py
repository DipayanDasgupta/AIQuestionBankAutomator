import os
import time
import google.generativeai as genai
from dotenv import load_dotenv

class GeminiAPI:
    """Manages multiple API keys, rotates them, and handles retries with a global cooldown."""
    def __init__(self):
        load_dotenv()
        self.keys = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 5) if os.getenv(f"GEMINI_API_KEY_{i}")]
        if not self.keys:
            raise ValueError("No GEMINI_API_KEY found in .env file. Please check your configuration.")
        self.current_key_index = 0
        
        # --- RATE LIMITING FIX ---
        # The cooldown period in seconds. 13s provides a small safety buffer for the 5 RPM limit (60s / 5 = 12s).
        self.cooldown_period = 13 
        # Track the time of the last API call.
        self.last_call_time = 0
        
        print(f"Loaded {len(self.keys)} Gemini API keys. Cooldown set to {self.cooldown_period} seconds.", flush=True)

    def get_response(self, prompt_text):
        # --- RATE LIMITING FIX: ENFORCE COOLDOWN ---
        # This block runs BEFORE every API call, guaranteeing the rate limit is respected.
        time_since_last_call = time.time() - self.last_call_time
        if time_since_last_call < self.cooldown_period:
            wait_time = self.cooldown_period - time_since_last_call
            print(f"    --> Cooldown active. Waiting for {wait_time:.2f} seconds...", flush=True)
            time.sleep(wait_time)

        max_retries_per_key = 3
        initial_wait_time = 5

        # Loop through keys for resiliency
        for _ in range(len(self.keys)):
            key = self.keys[self.current_key_index]
            key_index_for_log = self.current_key_index
            
            # Update last call time immediately before the attempt
            self.last_call_time = time.time()
            
            wait_time = initial_wait_time
            for retry_attempt in range(max_retries_per_key):
                try:
                    print(f"    --> Attempting API call with Key Index {key_index_for_log} (Attempt {retry_attempt + 1}/{max_retries_per_key})...", flush=True)
                    genai.configure(api_key=key)
                    safety_settings = [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                    # Using the model you requested
                    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)
                    
                    response = model.generate_content(prompt_text)
                    
                    # After a successful call, rotate to the next key for the *next* request
                    self.current_key_index = (self.current_key_index + 1) % len(self.keys)
                    
                    if not response.parts:
                        print(f"    --> Response blocked by safety settings. Rotating key.", flush=True)
                        break 
                    
                    return response.text

                except Exception as e:
                    error_str = str(e)
                    print(f"    --> API Error with Key Index {key_index_for_log}: {error_str[:90]}...", flush=True)
                    if "429" in error_str:
                        print(f"    --> Rate limit error hit. Waiting for {wait_time}s before retrying.", flush=True)
                        time.sleep(wait_time)
                        wait_time *= 2 # Exponential backoff
                        # Also update the last call time after a failed attempt's wait period
                        self.last_call_time = time.time()
                    else:
                        print(f"    --> Non-retriable error. Rotating to next key.", flush=True)
                        # Rotate key on non-429 error
                        self.current_key_index = (self.current_key_index + 1) % len(self.keys)
                        break # Break from retries for this key
        
        print("    --> All API keys failed for this request. Skipping.", flush=True)
        return None

# Initialize a single, global API manager for the whole pipeline
gemini_manager = GeminiAPI()