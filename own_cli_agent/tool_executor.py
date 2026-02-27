import subprocess
import re
from pathlib import Path
from .config import TEMP_PROJECT_DIR

class ToolExecutor:
    """Executes tools requested by the model (like running code or writing files)."""

    def __init__(self,permissions_manager,log_display,app_instance):
        self.permissions=permissions_manager
        self.log_display=log_display
        self.app=app_instance
        self.project_dir=Path.cwd() / "project_folder"

    def set_project_dir(self, project_path: Path) -> None:
        """Set the project directory for file operations."""
        self.project_dir=project_path
        self.project_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # INTERNAL: Clean model garbage (markdown / quotes / etc)
    # ---------------------------------------------------------
    def _clean_content(self,content:str)->str:
        content=content.strip()

        # Remove triple backtick blocks
        if content.startswith("```"):
            content=re.sub(r"^```[a-zA-Z0-9]*\n","",content)
            content=re.sub(r"\n```$","",content)

        # Remove leading/trailing triple quotes
        content=re.sub(r'^"""\n?','',content)
        content=re.sub(r'\n?"""$','',content)

        # Decode common HTML entities
        content=content.replace("&#34;",'"')
        content=content.replace("&lt;","<")
        content=content.replace("&gt;",">")
        content=content.replace("&amp;","&")

        return content.strip()

    # ---------------------------------------------------------
    # INTERNAL: Detect correct extension from content
    # ---------------------------------------------------------
    def _detect_extension(self,path:str,content:str)->str:
        ext=Path(path).suffix.lower()
        lower=content.lower()

        # If already valid and not markdown, keep it
        if ext and ext!=".md":
            return path

        # Detect type
        if "<!doctype html" in lower or "<html" in lower:
            return Path(path).with_suffix(".html").name

        if "function " in lower or "console.log" in lower:
            return Path(path).with_suffix(".js").name

        if "body {" in lower or "@media" in lower:
            return Path(path).with_suffix(".css").name

        if "def " in lower and ":" in lower:
            return Path(path).with_suffix(".py").name

        # Default fallback
        return Path(path).with_suffix(".txt").name

    # ---------------------------------------------------------
    # FILE WRITE
    # ---------------------------------------------------------
    def write_file(self,path:str,content:str)->str:

        if not self.permissions.is_allowed('allow_file_io'):
            return "TOOL:ERROR: File I/O is blocked by permissions. Change permissions.json to enable."

        if '..' in path or path.startswith('/'):
            return "TOOL:ERROR: Invalid path. Path must be relative and inside the project folder."

        cleaned=self._clean_content(content)

        if len(cleaned)<20 or not any(x in cleaned for x in ["<","{",";","def ","function "]):
            return "TOOL:ERROR: Model returned non-code content. Refusing to write file."

        corrected_name=self._detect_extension(path,cleaned)

        full_path=self.project_dir / corrected_name
        full_path.parent.mkdir(parents=True,exist_ok=True)

        try:
            with open(full_path,'w',encoding='utf-8') as f:
                f.write(cleaned)

            self.log_display.write(f"[TOOL:INFO] File written successfully: {full_path.relative_to(Path.cwd())}")
            return f"TOOL:SUCCESS: File written: {corrected_name}"

        except Exception as e:
            self.app._log_error_to_file(f"Tool Error: Failed to write file {corrected_name}",e)
            self.log_display.write(f"[TOOL:ERROR] Failed to write file {corrected_name}: {e}")
            return f"TOOL:ERROR: Failed to write file {corrected_name}: {e}"

    # ---------------------------------------------------------
    # RUN CODE
    # ---------------------------------------------------------
    def run_code(self,command:str)->str:

        if not self.permissions.is_allowed('allow_code_execution'):
            return "TOOL:ERROR: Code execution is blocked by permissions. Change permissions.json to enable."

        self.log_display.write(f"[TOOL:EXEC] Running command: '{command}' in {self.project_dir}")

        try:
            result=subprocess.run(
                command,
                cwd=self.project_dir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )

            output=result.stdout.strip()
            error=result.stderr.strip()

            if result.returncode==0:
                self.log_display.write("[TOOL:SUCCESS] Command executed (Code 0).")
                if output:
                    self.log_display.write(output)
                return f"TOOL:SUCCESS: OUTPUT:\n{output}"

            stderr_trim=error[:500] + ("..." if len(error)>500 else "")
            self.app._log_error_to_file(f"Tool Error: Command failed (Code {result.returncode})",None)
            self.log_display.write(f"[TOOL:ERROR] Command failed (Code {result.returncode}).")

            return f"TOOL:ERROR: Command failed (Code {result.returncode}).\nStderr:\n{stderr_trim}\nOutput:\n{output}"

        except subprocess.TimeoutExpired:
            self.app._log_error_to_file("Tool Error: Command timed out",None)
            self.log_display.write("[TOOL:ERROR] Command timed out after 300 seconds.")
            return "TOOL:ERROR: Command timed out after 300 seconds."

        except Exception as e:
            self.app._log_error_to_file("Tool Error: Execution failed",e)
            self.log_display.write(f"[TOOL:ERROR] Execution failed: {e}")
            return f"TOOL:ERROR: Execution failed: {e}"
