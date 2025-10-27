# model_manager.py

import json
import time
import requests
import traceback
from requests.exceptions import RequestException, HTTPError
from .config import TEMP_PROJECT_DIR # Relative import

class ModelManager:
    """Manages LLM API calls, handles Ollama, external providers, and response parsing."""

    # Note: app_instance is passed to allow access to the global file logging method
    def __init__(self, config_manager, log_display, app_instance):
        self.config=config_manager
        self.log_display=log_display  
        self.app=app_instance # Reference to the main App for logging

    def call_ollama(self, model, messages, provider):
        """Handles the Ollama API call specifically."""
                
        # --- STATUS UPDATE: This is the line that confirms the request is running ---
        self.log_display.write(f"[STATUS] Running your query, please wait...")
                
        base_url=provider['base_url']
                
        # Ensure URL points to the chat endpoint
        if '/api/' in base_url:
            base_url=base_url.split('/api/')[0]
                    
        url=f"{base_url}/api/chat"
                
        # CRITICAL: Agent model gets higher temperature
        temperature=0.7 if model == self.config.get_default_model('agent') else 0.3

        data={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }
                
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
                
        try:
            # The timeout is very long (5920 seconds)
            response=requests.post(url, headers=headers, json=data, timeout=5920)
            response.raise_for_status()
                    
            # Ollama /api/chat response structure
            result=response.json()
            if result.get('message') and result['message'].get('content'):
                return result['message']['content']
                        
            return "ERROR: Ollama response format unexpected."
                    
        except HTTPError as e:
            status_code=e.response.status_code if e.response is not None else 'Unknown'
            error_details=e.response.text if e.response is not None else str(e)
                    
            # Log detailed error to file
            self.app._log_error_to_file(
                f"Ollama HTTP Error {status_code} for model {model}", 
                e
            )

            # Extract a snippet of the error detail for the console log
            error_text=error_details.replace('\n', ' ').strip()
            detail_snippet=error_text[error_text.find('{'):]

            self.log_display.write(f"[MODEL:ERROR] Ollama request failed with HTTP Status {status_code}. Details: {detail_snippet[:100]}...")
            return f"ERROR: Ollama returned HTTP Status {status_code}. Check if the model '{model}' is pulled and running."
                    
        except RequestException as e:
            # Log detailed error to file
            self.app._log_error_to_file(
                f"Ollama Connection/Timeout Error to {provider['base_url']}", 
                e
            )

            self.log_display.write(f"[MODEL:ERROR] Ollama request failed (Connection/Timeout): {e}")
            return f"ERROR: Could not connect to Ollama ({e}). Is 'ollama serve' running?"

    def call_external(self, model, messages, provider):
        """Placeholder for external API call logic."""
        self.log_display.write(f"[MODEL:WARNING] External API call requested for {model} but logic is not implemented.")
        return f"ERROR: External API provider '{provider['name']}' not implemented."

    def call_model(self, model_name, messages, mode='chat'):
        """Main dispatcher for API calls."""
        provider=self.config.get_provider(model_name)
                
        if not provider:
            error_msg=f"Model '{model_name}' not found or its provider is disabled."
            self.app._log_error_to_file(
                f"Configuration Error: {error_msg}. Check config.json and provider list.",
                None
            )
            return f"ERROR: {error_msg}"

        self.log_display.write(f"[MODEL:INFO] Calling {provider['name']} with model {model_name}...")

        if provider['type'] == 'ollama':
            return self.call_ollama(model_name, messages, provider)
        elif provider['type'] == 'external':
            return self.call_external(model_name, messages, provider)
                    
        return f"ERROR: Unknown provider type '{provider['type']}'"
