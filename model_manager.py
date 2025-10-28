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

        # Cache for Ollama models to avoid frequent API calls
        self._ollama_model_cache=[]
        self._last_ollama_fetch=0
        self._cache_duration=300 # Cache for 5 minutes (300 seconds)

    # --- NEW: Model Discovery for Autocompletion ---
    def get_ollama_models(self) -> list[str]:
        """
        Retrieves a list of available models from the configured Ollama instance.
        Uses caching to reduce API load.
        """
        ollama_provider=self.config.get_provider_by_type('ollama')

        if not ollama_provider:
            self.log_display.write("[MODEL:WARN] No Ollama provider found in config. Cannot fetch models.")
            return []

        # Check cache freshness
        if time.time() - self._last_ollama_fetch < self._cache_duration and self._ollama_model_cache:
            return self._ollama_model_cache

        base_url=ollama_provider['base_url']
        # Use the list endpoint
        url=f"{base_url}/api/tags"

        try:
            response=requests.get(url, timeout=10) # Short timeout for listing models
            response.raise_for_status()
            
            result=response.json()
            if 'models' in result:
                model_names=[m['name'] for m in result['models']]
                self._ollama_model_cache=model_names
                self._last_ollama_fetch=time.time()
                return model_names
            
            return []
        
        except RequestException as e:
            # Log the error to the console, but don't log to file unless critical
            self.log_display.write(f"[MODEL:ERROR] Failed to connect to Ollama for model list: {e}")
            return []
    
    # --- API Call Logic ---

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
        # Use a more explicit check for agent mode instead of model name comparison
        is_agent_mode=messages[0]['role'] == 'system' and 'tool' in messages[0]['content'].lower()
        temperature=0.7 if is_agent_mode else 0.3

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
            # Use regex to safely extract JSON snippet for display
            detail_snippet_match=re.search(r'\{.*\}', error_text)
            detail_snippet=detail_snippet_match.group(0) if detail_snippet_match else error_text

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
            # Note: External logic still needs full implementation for production use
            return self.call_external(model_name, messages, provider)
                    
        return f"ERROR: Unknown provider type '{provider['type']}'"
