# model_manager.py
import os
import re
import json
import time
import uuid
import requests
import traceback
from requests.exceptions import RequestException, HTTPError
from .config import TEMP_PROJECT_DIR # Relative import

# Identifies this client to OpenCode Go. The Go docs ask clients to send their
# own product user agent and a stable per-conversation x-opencode-session.
CLIENT_NAME = "own-cli-agent"
CLIENT_VERSION = "1.0"
USER_AGENT = f"{CLIENT_NAME}/{CLIENT_VERSION}"

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

        # OpenCode session/project identifiers. x-opencode-session must stay
        # stable for every request in a conversation, but change on reset.
        self.session_id=str(uuid.uuid4())
        self.project_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"own-cli-agent:{os.getcwd()}"))
        self._opencode_model_cache={}
        self._last_opencode_fetch=0
        # Models that reject /chat/completions and only speak the Anthropic
        # Messages protocol (e.g. MiniMax/Qwen on OpenCode Go).
        self._anthropic_models=set()

    def reset_session(self):
        """Start a new OpenCode conversation (new routing/prompt-cache key)."""
        self.session_id=str(uuid.uuid4())

    def _resolve_api_key(self, provider) -> str | None:
        """Expand ${ENV_VAR} placeholders in a provider's api_key."""
        raw_key=str(provider.get('api_key') or '').strip()
        if not raw_key or raw_key.upper() in ('NA', 'NONE'):
            return ''

        missing=[]

        def replace(match):
            var= match.group(1) or match.group(2)
            value=os.environ.get(var)
            if value is None:
                missing.append(var)
                return ''
            return value

        resolved=re.sub(
            r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)',
            replace,
            raw_key
        )

        if missing:
            self.log_display.write(
                f"[MODEL:ERROR] Missing environment variable(s) for provider "
                f"'{provider.get('name', 'unknown')}': {', '.join(missing)}"
            )
            return None

        return resolved.strip()

    def _normalize_openai_messages(self, messages):
        """Convert internal messages to a format accepted by OpenAI-compatible APIs."""
        normalized=[]
        for message in messages:
            role=message.get('role', 'user')
            content=message.get('content', '')
            if content is None:
                content=''
            elif not isinstance(content, str):
                content=str(content)

            # The agent loop adds tool output as role "tool" without a
            # tool_call_id. OpenAI-compatible endpoints reject that, so fold
            # it into a user message instead.
            if role == 'tool':
                role='user'
                content=f"[Tool output]\n{content}"
            elif role not in ('system', 'user', 'assistant'):
                role='user'

            normalized.append({"role": role, "content": content})

        return normalized

    def _opencode_headers(self, api_key: str) -> dict:
        """Headers required/recommended for OpenCode Go requests."""
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': USER_AGENT,
            'x-opencode-client': CLIENT_NAME,
            'x-opencode-project': self.project_id,
            'x-opencode-session': self.session_id,
            'x-opencode-request': f"msg_{uuid.uuid4().hex}",
        }
        if api_key:
            headers['Authorization']=f"Bearer {api_key}"
        return headers

    def get_opencode_models(self, provider) -> list[str]:
        """Retrieve models from an OpenCode/OpenAI-compatible provider."""
        cache_key=provider.get('base_url', '')
        if (
            time.time() - self._last_opencode_fetch < self._cache_duration
            and self._opencode_model_cache.get(cache_key)
        ):
            return self._opencode_model_cache[cache_key]

        api_key=self._resolve_api_key(provider)
        if api_key is None:
            return []

        url=f"{provider['base_url'].rstrip('/')}/models"
        try:
            response=requests.get(
                url,
                headers=self._opencode_headers(api_key),
                timeout=10
            )
            response.raise_for_status()
            result=response.json()

            entries=result.get('data', result.get('models', []))
            model_names=[]
            for entry in entries:
                if isinstance(entry, str):
                    model_names.append(entry)
                elif isinstance(entry, dict):
                    model_id=entry.get('id') or entry.get('name')
                    if model_id:
                        model_names.append(model_id)

            self._opencode_model_cache[cache_key]=sorted(set(model_names))
            self._last_opencode_fetch=time.time()
            return self._opencode_model_cache[cache_key]
        except (RequestException, ValueError) as e:
            self.log_display.write(
                f"[MODEL:WARN] Could not fetch model list from {provider.get('name', 'provider')}: {e}"
            )
            return []

    def get_available_models(self) -> list[str]:
        """Return models from all enabled providers for autocompletion."""
        models=[]
        for provider in self.config.config.get('providers', []):
            if not provider.get('enabled'):
                continue
            provider_type=provider.get('type', '')
            if provider_type == 'ollama':
                models.extend(self.get_ollama_models())
            elif provider_type in ('opencode', 'openai', 'openai-compatible'):
                models.extend(self.get_opencode_models(provider))
        return sorted(set(models))

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

    def call_ollama(self, model, messages, provider, mode='chat'):
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
            # Faster timeout for chat (30 seconds), longer for agent (120 seconds)
            timeout=30 if mode == 'chat' else 120
            response=requests.post(url, headers=headers, json=data, timeout=timeout)
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

    def _anthropic_url(self, base_url: str) -> str:
        """Derive the Anthropic Messages endpoint from an OpenAI base URL."""
        base_url=base_url.rstrip('/')
        if base_url.endswith('/openai/v1'):
            base_url=base_url[:-len('/openai/v1')] + '/anthropic/v1'
        elif not base_url.endswith('/v1'):
            base_url=f"{base_url}/v1"
        return f"{base_url}/messages"

    def _normalize_anthropic_messages(self, messages):
        """Convert internal messages to Anthropic Messages format."""
        system_parts=[]
        normalized=[]

        for message in messages:
            role=message.get('role', 'user')
            content=message.get('content', '')
            if content is None:
                content=''
            elif not isinstance(content, str):
                content=str(content)

            if role == 'system':
                system_parts.append(content)
                continue

            if role == 'tool':
                role='user'
                content=f"[Tool output]\n{content}"
            elif role not in ('user', 'assistant'):
                role='user'

            # Anthropic expects alternating user/assistant turns.
            if normalized and normalized[-1]['role'] == role:
                normalized[-1]['content'] += f"\n\n{content}"
            else:
                normalized.append({"role": role, "content": content})

        if not normalized:
            normalized.append({"role": "user", "content": "Continue."})

        system="\n\n".join(part for part in system_parts if part)
        return system, normalized

    def _call_opencode_anthropic(self, model, messages, provider, api_key, mode='chat'):
        """Call the Anthropic Messages protocol used by some OpenCode Go models."""
        base_url=provider['base_url']
        url=self._anthropic_url(base_url)
        system, normalized=self._normalize_anthropic_messages(messages)

        data={
            "model": model,
            "max_tokens": 8192,
            "messages": normalized,
            "temperature": 0.7 if mode == 'agent' else 0.3,
        }
        if system:
            data['system']=system

        headers=self._opencode_headers(api_key)
        # The Anthropic protocol authenticates with x-api-key, not Bearer.
        headers.pop('Authorization', None)
        headers['x-api-key']=api_key
        headers['anthropic-version']='2023-06-01'

        try:
            timeout=60 if mode == 'chat' else 180
            response=requests.post(url, headers=headers, json=data, timeout=timeout)
            response.raise_for_status()
            result=response.json()
        except HTTPError as e:
            status_code=e.response.status_code if e.response is not None else 'Unknown'
            error_details=e.response.text if e.response is not None else str(e)
            self.app._log_error_to_file(
                f"OpenCode Anthropic HTTP Error {status_code} for model {model}",
                e
            )
            error_text=error_details.replace('\n', ' ').strip()
            self.log_display.write(
                f"[MODEL:ERROR] OpenCode Anthropic request failed with HTTP Status "
                f"{status_code}. Details: {error_text[:160]}"
            )
            return f"ERROR: OpenCode returned HTTP Status {status_code}."
        except RequestException as e:
            self.app._log_error_to_file(
                f"OpenCode Anthropic Connection/Timeout Error to {url}",
                e
            )
            self.log_display.write(f"[MODEL:ERROR] OpenCode request failed (Connection/Timeout): {e}")
            return f"ERROR: Could not connect to OpenCode ({e})."
        except ValueError as e:
            self.app._log_error_to_file("OpenCode returned invalid JSON", e)
            return "ERROR: OpenCode returned an unexpected response."

        content=result.get('content')
        if isinstance(content, list):
            text_parts=[
                block.get('text', '')
                for block in content
                if isinstance(block, dict) and block.get('type') == 'text'
            ]
            text=''.join(text_parts).strip()
            if text:
                return text

            thinking_parts=[
                block.get('thinking', '')
                for block in content
                if isinstance(block, dict) and block.get('type') == 'thinking'
            ]
            thinking=''.join(thinking_parts).strip()
            if thinking:
                return thinking

        self.log_display.write(
            f"[MODEL:WARN] OpenCode returned an empty message "
            f"(stop_reason={result.get('stop_reason')})."
        )
        return "ERROR: OpenCode returned an empty response."

    def call_opencode(self, model, messages, provider, mode='chat'):
        """Call an OpenCode Go / OpenAI-compatible chat completions endpoint."""
        self.log_display.write(f"[STATUS] Running your query, please wait...")

        api_key=self._resolve_api_key(provider)
        if api_key is None:
            return (
                "ERROR: API key could not be resolved. Set the environment "
                "variable referenced by the provider's api_key."
            )

        if model in self._anthropic_models:
            return self._call_opencode_anthropic(
                model, messages, provider, api_key, mode
            )

        base_url=provider['base_url'].rstrip('/')
        if base_url.endswith('/chat/completions'):
            url=base_url
        else:
            url=f"{base_url}/chat/completions"

        is_agent_mode=mode == 'agent'
        data={
            "model": model,
            "messages": self._normalize_openai_messages(messages),
            "stream": False,
            "temperature": 0.7 if is_agent_mode else 0.3,
        }

        headers=self._opencode_headers(api_key)

        try:
            # Allow longer for agent loops, which produce much larger responses.
            timeout=60 if mode == 'chat' else 180
            response=requests.post(url, headers=headers, json=data, timeout=timeout)
            response.raise_for_status()
            result=response.json()
        except HTTPError as e:
            status_code=e.response.status_code if e.response is not None else 'Unknown'
            error_details=e.response.text if e.response is not None else str(e)

            # Some Go models only implement the Anthropic Messages protocol.
            # Detect that once, cache it, and transparently retry.
            if status_code == 400 and 'ModelProtocolUnsupported' in error_details:
                self._anthropic_models.add(model)
                self.log_display.write(
                    f"[MODEL:INFO] '{model}' uses the Anthropic protocol; retrying."
                )
                return self._call_opencode_anthropic(
                    model, messages, provider, api_key, mode
                )

            self.app._log_error_to_file(
                f"OpenCode HTTP Error {status_code} for model {model}",
                e
            )

            error_text=error_details.replace('\n', ' ').strip()
            detail_snippet_match=re.search(r'\{.*\}', error_text)
            detail_snippet=detail_snippet_match.group(0) if detail_snippet_match else error_text

            hint=""
            if status_code == 401:
                hint=" Check that OPENCODE_API_KEY is valid."
            elif status_code == 403:
                hint=" The API key may not have access to this model."
            elif status_code == 404:
                hint=" Check the provider base_url and model name."
            elif status_code == 429:
                hint=" Rate limit or usage limit reached; try again later."
            elif status_code == 400 and 'session' in error_text.lower():
                hint=" The x-opencode-session header was rejected."

            self.log_display.write(
                f"[MODEL:ERROR] OpenCode request failed with HTTP Status {status_code}. "
                f"Details: {detail_snippet[:160]}{hint}"
            )
            return f"ERROR: OpenCode returned HTTP Status {status_code}.{hint}"

        except RequestException as e:
            self.app._log_error_to_file(
                f"OpenCode Connection/Timeout Error to {provider['base_url']}",
                e
            )
            self.log_display.write(f"[MODEL:ERROR] OpenCode request failed (Connection/Timeout): {e}")
            return f"ERROR: Could not connect to OpenCode ({e})."

        except ValueError as e:
            self.app._log_error_to_file("OpenCode returned invalid JSON", e)
            self.log_display.write("[MODEL:ERROR] OpenCode returned a non-JSON response.")
            return "ERROR: OpenCode returned an unexpected response."

        try:
            choice=result['choices'][0]
        except (KeyError, IndexError, TypeError):
            self.app._log_error_to_file(
                f"OpenCode response format unexpected for model {model}",
                None
            )
            self.log_display.write("[MODEL:ERROR] OpenCode response did not contain choices.")
            return "ERROR: OpenCode response format unexpected."

        message=choice.get('message') or {}
        content=message.get('content')

        # Some providers expose reasoning separately when content is empty.
        if not content:
            content=message.get('reasoning_content') or message.get('reasoning')

        if isinstance(content, list):
            parts=[]
            for part in content:
                if isinstance(part, dict):
                    parts.append(part.get('text', ''))
                else:
                    parts.append(str(part))
            content=''.join(parts)

        if content:
            return content

        finish_reason=choice.get('finish_reason')
        self.log_display.write(
            f"[MODEL:WARN] OpenCode returned an empty message (finish_reason={finish_reason})."
        )
        return "ERROR: OpenCode returned an empty response."

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
            return self.call_ollama(model_name, messages, provider, mode)
        elif provider['type'] in ('opencode', 'openai', 'openai-compatible'):
            return self.call_opencode(model_name, messages, provider, mode)
        elif provider['type'] == 'external':
            # Note: External logic still needs full implementation for production use
            return self.call_external(model_name, messages, provider)
                    
        return f"ERROR: Unknown provider type '{provider['type']}'"

