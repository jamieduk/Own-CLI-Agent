# config.py

import json
from pathlib import Path

# --- GLOBAL CONSTANTS ---

APP_ID="own_cli_agent"
CONFIG_DIR=Path.home() / f".{APP_ID}"
CONFIG_FILE=CONFIG_DIR / "config.json"
PERMISSIONS_FILE=CONFIG_DIR / "permissions.json"
MEMORIES_FILE=CONFIG_DIR / "memories.json"
HISTORY_FILE=CONFIG_DIR / "history.json"
# ERROR_LOG_FILE is kept in the main application's working directory
ERROR_LOG_FILE=Path.cwd() / "error.log"
TEMP_PROJECT_DIR=Path.cwd() / "project_folder"

# NOTE: Model defaults changed to use the user's available deepseek model for chat.
DEFAULT_CONFIG={
    "providers": [
        {
            "name": "Ollama Local",
            "enabled": True,
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "chat_model": "deepseek-r1:7b",
            "agent_model": "llama3.1:8b:latest",
            "image_model": "llava-phi3:latest",
            "api_key": "NA"
        },
    ],
    "default_chat_model": "deepseek-r1:7b",
    "default_agent_model": "llama3.1:8b:latest",
}

DEFAULT_PERMISSIONS={
    "allow_file_io": True,
    "allow_code_execution": True,
    "allow_auto_browse": True,
    "allow_host_control": True
}

# --- CONFIGURATION CLASSES ---

class ConfigManager:
    """Handles reading and writing the configuration file."""
    def __init__(self):
        self.config=DEFAULT_CONFIG.copy()
        self.config_loaded=False
        # NOTE: _ensure_config_dir is now called inside __init__ to manage paths
        self._ensure_config_dir()
        self._load_config()

    def _ensure_config_dir(self):
        """Ensure the configuration directory exists."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Note: TEMP_PROJECT_DIR will be ensured in the main app on mount

    def _load_config(self):
        """Load configuration from file or use defaults."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config=json.load(f)
                    # Merge loaded config with defaults, preserving the 'providers' list structure
                    self.config={**DEFAULT_CONFIG, **loaded_config}
                    if 'providers' in loaded_config:
                        self.config['providers']=loaded_config['providers']
                    self.config_loaded=True
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {CONFIG_FILE}. Using default config.")
                self._save_config()
            except IOError:
                self._save_config()
        else:
            self._save_config()

    def _save_config(self):
        """Save the current configuration to file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Error saving config file {CONFIG_FILE}: {e}")

    def get_provider(self, model_name):
        """Find the provider configuration for a given model name."""
        for provider in self.config.get("providers", []):
            if provider.get("enabled"):
                if (provider.get("chat_model") == model_name or 
                    provider.get("agent_model") == model_name or 
                    provider.get("image_model") == model_name):
                    return provider
        return None

    def get_default_model(self, mode):
        """Get the default model name for a given mode ('chat' or 'agent')."""
        key=f"default_{mode}_model"
        return self.config.get(key, DEFAULT_CONFIG.get(key))

    def get_provider_by_type(self, provider_type: str) -> dict | None:
        """
        Retrieves the first enabled provider matching the specified type (e.g., 'ollama').
        Returns the provider dictionary or None if not found/enabled.
        """
        for provider in self.config.get('providers', []):
            if provider.get('type') == provider_type and provider.get('enabled', False):
                return provider
        return None

        
class PermissionsManager:
    """Handles reading and writing the permissions file."""
    def __init__(self):
        self.permissions=DEFAULT_PERMISSIONS.copy()
        self._load_permissions()

    def _load_permissions(self):
        """Load permissions from file or use defaults."""
        if PERMISSIONS_FILE.exists():
            try:
                with open(PERMISSIONS_FILE, 'r') as f:
                    loaded_permissions=json.load(f)
                    self.permissions={
                        key: loaded_permissions.get(key, DEFAULT_PERMISSIONS[key])
                        for key in DEFAULT_PERMISSIONS
                    }
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {PERMISSIONS_FILE}. Using default permissions.")
                self._save_permissions()
            except IOError:
                self._save_permissions()
        else:
            self._save_permissions()

    def _save_permissions(self):
        """Save the current permissions to file."""
        try:
            with open(PERMISSIONS_FILE, 'w') as f:
                json.dump(self.permissions, f, indent=4)
        except IOError as e:
            print(f"Error saving permissions file {PERMISSIONS_FILE}: {e}")

    def is_allowed(self, permission_key):
        """Check if a specific permission is allowed."""
        return self.permissions.get(permission_key, False)
