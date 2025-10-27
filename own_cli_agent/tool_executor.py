# tool_executor.py

import subprocess
from pathlib import Path
from .config import TEMP_PROJECT_DIR # Relative import

class ToolExecutor:
    """Executes tools requested by the model (like running code or writing files)."""
    def __init__(self, permissions_manager, log_display, app_instance):
        self.permissions=permissions_manager
        self.log_display=log_display  
        self.app=app_instance # Reference to the main App for logging
                
    def write_file(self, path: str, content: str) -> str:
        """Writes content to a file in the project directory."""
        if not self.permissions.is_allowed('allow_file_io'):
            return "TOOL:ERROR: File I/O is blocked by permissions. Change permissions.json to enable."

        # Security check: Ensure path does not try to escape the project folder
        if '..' in path or path.startswith('/'):
            return "TOOL:ERROR: Invalid path. Path must be relative and inside the project folder."
                
        full_path=TEMP_PROJECT_DIR / path
                
        full_path.parent.mkdir(parents=True, exist_ok=True)
                
        try:
            with open(full_path, 'w') as f:
                f.write(content)
            self.log_display.write(f"[TOOL:INFO] File written successfully: {full_path.relative_to(Path.cwd())}")
            return f"TOOL:SUCCESS: File written: {path}"
        except Exception as e:
            self.app._log_error_to_file(f"Tool Error: Failed to write file {path}", e)
            self.log_display.write(f"[TOOL:ERROR] Failed to write file {path}: {e}")
            return f"TOOL:ERROR: Failed to write file {path}: {e}"

    def run_code(self, command: str) -> str:
        """Executes a shell command in the project directory."""
        if not self.permissions.is_allowed('allow_code_execution'):
            return "TOOL:ERROR: Code execution is blocked by permissions. Change permissions.json to enable."

        self.log_display.write(f"[TOOL:EXEC] Running command: '{command}' in {TEMP_PROJECT_DIR.relative_to(Path.home())}")

        try:
            result=subprocess.run(
                command,
                cwd=TEMP_PROJECT_DIR,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
                        
            output=result.stdout
            error=result.stderr
                        
            # Format output/error clearly for the agent
            if result.returncode == 0:
                # --- START FIX: Return raw output to agent ---
                
                # 1. Log to TUI for human viewing
                self.log_display.write(f"[TOOL:SUCCESS] Command executed (Code 0).")
                self.log_display.write(f"--- STDOUT ---")
                self.log_display.write(output.strip()) # Print cleaned output to TUI
                self.log_display.write(f"--------------")
                
                # 2. Return to AGENT: Return the RAW output, only prefixed by the SUCCESS tag.
                # .strip() removes the trailing newline (\n) from the print statement, ensuring clean parsing.
                return f"TOOL:SUCCESS: OUTPUT:\n{output.strip()}" 
                
                # --- END FIX ---
            else:
                stderr_formatted=f"Stderr (Truncated):\n{error[:500]}..." if len(error) > 500 else f"Stderr:\n{error}"
                # CRITICAL: Log detailed command error to file
                self.app._log_error_to_file(f"Tool Error: Command failed (Code {result.returncode})", None)
                self.log_display.write(f"[TOOL:ERROR] Command failed (Code {result.returncode}). {stderr_formatted.splitlines()[0]}...")
                
                return f"TOOL:ERROR: Command failed (Code {result.returncode}).\n{stderr_formatted}\nOutput:\n{output.strip()}"

        except subprocess.TimeoutExpired:
            self.app._log_error_to_file("Tool Error: Command timed out", None)
            self.log_display.write("[TOOL:ERROR] Command timed out after 300 seconds.")
            return "TOOL:ERROR: Command timed out after 30 seconds."
        except Exception as e:
            self.app._log_error_to_file("Tool Error: Execution failed", e)
            self.log_display.write(f"[TOOL:ERROR] Execution failed: {e}")
            return f"TOOL:ERROR: Execution failed: {e}"
