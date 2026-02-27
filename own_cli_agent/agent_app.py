import json
import os
import time
import re
import traceback
from pathlib import Path
import sys
import subprocess
import time
import pyperclip
from datetime import datetime
from utils import google_search, speak_response

try:
    pyperclip.copy=pyperclip.copy_tk
except AttributeError:
    pass
    
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, RichLog
from textual.containers import Container
from textual.binding import Binding

from .config import (
    ConfigManager, PermissionsManager, 
    HISTORY_FILE, ERROR_LOG_FILE, CONFIG_FILE, TEMP_PROJECT_DIR
)
from .model_manager import ModelManager
from .tool_executor import ToolExecutor

    
class OwnCLIApp(App):
    """The main Textual application for the CLI agent."""
    
    # CSS remains inline for simplicity, as it's part of the Textual setup
    CSS="""
    .dark Header {
        background: #1E1E1E;
        color: gold;
    }
    #app-grid {
        grid-size: 2 1;
        grid-columns: 2fr 8fr;
        height: 100%;
        overflow: hidden;
    }
    #options-panel {
        display: none;
        width: 100%;
        height: 100%;
        background: #282A36;
        color: #F8F8F2;
        border-right: heavy #50FA7B;
        padding: 1;
        text-align: left;
        overflow-y: auto;
    }
    #main-content {
        height: 100%;
        layout: vertical;
    }
    #log-display {
        height: 1fr;
        background: #1E1E1E;
        color: #F8F8F2;
        border: solid #282A36;
        padding: 0 1;
        overflow-y: auto;
        width: 100%;
    }
    #main-input {
        height: auto;
        min-height: 3;
        margin-top: 1;
        border: round #50FA7B;
        padding: 0 1;
    }
    Footer {
        background: #1E1E1E;
        color: #6272A4;
    }
    .status-message {
        text-align: center;
        width: 100%;
        color: #BD93F9;
    }
    """
    
    BINDINGS=[
        Binding("ctrl+o", "toggle_options", "Toggle Options", key_display="Ctrl+O"),
        Binding("ctrl+q", "quit", "Quit", key_display="Ctrl+Q"),
        Binding("ctrl+r", "reset_session", "Reset", key_display="Ctrl+R"),
        Binding("ctrl+d", "show_tools", "Show Tools", key_display="Ctrl+D"),
        Binding("ctrl+c", "copy_last_response", "Copy", key_display="Ctrl+C"),
        Binding("ctrl+v", "paste_to_input", "Paste", key_display="Ctrl+V"),
        Binding("ctrl+x", "cut_input", "Cut", key_display="Ctrl+X"),
    ]

    MAX_AGENT_STEPS=3000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config=ConfigManager()
        self.permissions=PermissionsManager()
        self.app_title="Own-CLI Agent (Ollama/Multi-Provider)"
        self.sub_title="Enter a goal or a message. Use /agent /chat /model"
        self.log_display=RichLog(id="log-display", highlight=True, markup=True)
        
        self.command_history=self._load_history()
        
        self.model_manager=ModelManager(self.config, self.log_display, self)
        self.tool_executor=ToolExecutor(self.permissions, self.log_display, self)
        self.chat_history=[]
        self.chat_personality: str | None = None  # Loaded from personality.txt
        self.session_mode='agent'
        
        # Load personality at startup
        self._load_personality()
        
        self.temp_model_override: str | None=None
        
        # --- NEW: Planning Mode & Checklist System ---
        self.planning_mode=True
        self.current_project_name: str | None=None
        self.project_subfolder: Path | None=None
        self.checklist: list[dict]=[]
        self.checklist_completed=False
        self.iteration_count=0
        self.max_iterations=50
        self.last_error: str | None=None
        self.planning_questions: list[str]=[]
        
        # --- Memory System: Store file contents for follow-up questions ---
        self.file_memory: dict[str, str] = {}  # filename -> content summary
        self.last_read_file: str | None = None
        self.last_requirements: str | None = None  # Store extracted requirements

    # --- Utility Methods ---
    def write_response_to_file(self, content: str) -> None:
        """
        Writes the final, clean response content to last.txt.
        
        The 'w' mode automatically creates the file if it doesn't exist 
        and overwrites it if it does.
        """
        FILE_PATH="last.txt"
        try:
            # Using "w" mode: write, create if not exists, overwrite if exists.
            with open(FILE_PATH, "w", encoding="utf-8") as f:
                f.write(content.strip())
        except Exception as e:
            # Simple logging of the error if file writing fails
            print(f"Error writing to {FILE_PATH}: {e}")


    def action_copy_cli_text(self) -> None:
        """Reads text from 'last.txt' and copies it to the system clipboard."""
        FILE_PATH="last.txt"
        text_to_copy=""
        
        # 1. Read the content from the file
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as f:
                text_to_copy=f.read().strip()
                
        except FileNotFoundError:
            self.call_after_refresh(
                lambda: self.log_display.write(f"[CLIPBOARD:FATAL] Copy failed: File {FILE_PATH} not found. Run a query first.")
            )
            return
        except Exception as e:
            self.call_after_refresh(
                lambda: self.log_display.write(f"[CLIPBOARD:FATAL] File read error: {type(e).__name__}")
            )
            return

        if not text_to_copy:
            self.call_after_refresh(
                lambda: self.log_display.write("[STATUS] Clipboard copy skipped: last.txt was empty.")
            )
            return

        # 2. Determine the command based on the environment (Same reliable logic)
        if 'TMUX' in os.environ:
            command=['tmux', 'load-buffer', '-']
            tool_name="tmux-buffer"
        else:
            # Fallback to the working CLI tool (xsel)
            command=['xsel', '--clipboard', '--input']
            tool_name="xsel-direct"

        try:
            # 3. Execute the command via subprocess.Popen
            p=subprocess.Popen(command, stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text_to_copy.encode('utf-8'))
            time.sleep(0.02) 

            self.call_after_refresh(
                lambda: self.log_display.write(f"[STATUS] Copied content of {FILE_PATH} via [bold cyan]{tool_name}[/bold cyan] (Ctrl+X) ✅")
            )

        except FileNotFoundError:
            self.call_after_refresh(
                lambda: self.log_display.write(f"[CLIPBOARD:FATAL] Copy failed: Required tool ({command[0]}) not found. Install xsel/tmux.")
            )
        except Exception as e:
            self.call_after_refresh(
                lambda: self.log_display.write(f"[CLIPBOARD:FATAL] Copy failed: {type(e).__name__}. Check permissions/environment.")
            )
            self._log_error_to_file("Clipboard attempt failed (File Read Action)", e)

    def action_copy_last_response(self) -> None:
        """Copy last response from last.txt to clipboard using multiple methods."""
        FILE_PATH="last.txt"
        text_to_copy=""
        
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as f:
                text_to_copy=f.read().strip()
        except FileNotFoundError:
            self.log_display.write(f"[CLIPBOARD] Copy failed: {FILE_PATH} not found.")
            return
        except Exception as e:
            self.log_display.write(f"[CLIPBOARD] File read error: {e}")
            return
            
        if not text_to_copy:
            self.log_display.write("[CLIPBOARD] Nothing to copy (empty file).")
            return
        
        # Try multiple methods for clipboard
        success=False
        methods=[
            ('xsel', ['xsel', '--clipboard', '--input']),
            ('xclip', ['xclip', '-selection', 'clipboard']),
            ('wl-paste', ['wl-paste']),
            ('tmux', ['tmux', 'load-buffer', '-']),
        ]
        
        for name, cmd in methods:
            try:
                p=subprocess.Popen(cmd, stdin=subprocess.PIPE, close_fds=True)
                p.communicate(input=text_to_copy.encode('utf-8'))
                success=True
                self.log_display.write(f"[CLIPBOARD] Copied via {name} (Ctrl+C) ✅")
                break
            except FileNotFoundError:
                continue
            except Exception:
                continue
        
        if not success:
            # Fallback: write to temp file
            temp_file=Path("/tmp/owncli_clipboard.txt")
            temp_file.write_text(text_to_copy)
            self.log_display.write(f"[CLIPBOARD] Saved to {temp_file}. Run 'xclip -paste' or manually copy.")

    def action_paste_to_input(self) -> None:
        """Paste from system clipboard to input field."""
        text=""
        
        # Try to read from clipboard using various methods
        methods=[
            ('xsel', ['xsel', '--clipboard', '--output']),
            ('xclip', ['xclip', '-selection', 'clipboard', '-o']),
            ('wl-paste', ['wl-paste']),
        ]
        
        for name, cmd in methods:
            try:
                p=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
                stdout, _=p.communicate()
                if stdout:
                    text=stdout.decode('utf-8', errors='replace').strip()
                    break
            except Exception:
                continue
        
        if not text:
            # Try pyperclip as fallback
            try:
                text=pyperclip.paste()
            except Exception:
                pass
        
        if text:
            input_widget=self.query_one("#main-input", Input)
            input_widget.insert_text_at_cursor(text)
            self.log_display.write("[CLIPBOARD] Pasted text to input ✅")
        else:
            self.log_display.write("[CLIPBOARD] No text in clipboard to paste.")

    def action_cut_input(self) -> None:
        """Cut selected text from input to clipboard."""
        input_widget=self.query_one("#main-input", Input)
        selected=input_widget.selected_text
        
        if selected:
            # Copy to clipboard
            try:
                subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE, close_fds=True).communicate(input=selected.encode('utf-8'))
            except Exception:
                try:
                    subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE, close_fds=True).communicate(input=selected.encode('utf-8'))
                except Exception:
                    pass
            
            # Delete selected text
            input_widget.delete()
            self.log_display.write("[CLIPBOARD] Cut text to clipboard ✅")
        else:
            self.log_display.write("[CLIPBOARD] No text selected to cut.")

    def _create_project_subfolder(self, project_name: str) -> Path:
        """Create a unique subfolder for a project based on timestamp and name."""
        safe_name=re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)[:50]
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name=f"{safe_name}_{timestamp}"
        project_dir=TEMP_PROJECT_DIR / folder_name
        project_dir.mkdir(parents=True, exist_ok=True)
        self.log_display.write(f"[PROJECT] Created subfolder: {project_dir.relative_to(Path.cwd())}")
        return project_dir

    def _init_checklist(self, prompt: str) -> list[dict]:
        """Initialize checklist based on the user's request."""
        checklist=[]
        prompt_lower=prompt.lower()
        
        # Core requirements
        checklist.append({"task": "Understand requirements", "completed": False, "description": "Analyze user request and clarify if needed"})
        checklist.append({"task": "Create project structure", "completed": False, "description": "Set up proper file/folder structure"})
        
        # Language-specific checks
        if any(x in prompt_lower for x in ['web', 'html', 'css', 'javascript', 'website', 'app']):
            checklist.append({"task": "Create HTML file", "completed": False, "description": "Create index.html with proper structure"})
            checklist.append({"task": "Create CSS styles", "completed": False, "description": "Create styles.css if needed"})
            checklist.append({"task": "Create JavaScript", "completed": False, "description": "Create script.js if needed"})
        
        if 'python' in prompt_lower or any(x in prompt_lower for x in ['game', 'tetris', 'script', 'cli']):
            checklist.append({"task": "Write Python code", "completed": False, "description": "Create main.py with working code"})
            checklist.append({"task": "Test Python code", "completed": False, "description": "Run and verify Python script works"})
        
        if 'game' in prompt_lower:
            checklist.append({"task": "Implement game logic", "completed": False, "description": "Create playable game mechanics"})
            checklist.append({"task": "Test game runs", "completed": False, "description": "Verify game starts and is playable"})
        
        checklist.append({"task": "Verify all files exist", "completed": False, "description": "Check all required files are created"})
        checklist.append({"task": "Final validation", "completed": False, "description": "Run final tests to confirm everything works"})
        
        return checklist

    def _update_checklist(self, task_name: str, completed: bool) -> None:
        """Mark a checklist task as completed."""
        for item in self.checklist:
            if item["task"] == task_name:
                item["completed"]=completed
                status="✅" if completed else "⬜"
                self.log_display.write(f"[CHECKLIST] {status} {task_name}")
                break

    def _check_all_completed(self) -> bool:
        """Check if all checklist items are completed."""
        if not self.checklist:
            return False
        return all(item["completed"] for item in self.checklist)

    def _get_incomplete_tasks(self) -> str:
        """Get list of incomplete tasks."""
        incomplete=[item["task"] for item in self.checklist if not item["completed"]]
        return ", ".join(incomplete) if incomplete else "None"
    
    def _load_history(self):
        """Loads command history from file."""
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_history(self):
        """Saves command history to file."""
        try:
            with open(HISTORY_FILE, 'w') as f:
                # Only save the last 50 unique commands
                history_to_save=list(dict.fromkeys(self.command_history))[-50:]
                json.dump(history_to_save, f, indent=4)
        except IOError as e:
            self.log_display.write(f"[ERROR] Failed to save history file: {e}")

    def _load_personality(self) -> str | None:
        """Load personality from personality.txt if it exists."""
        personality_file = Path("personality.txt")
        if personality_file.exists():
            try:
                with open(personality_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        self.chat_personality = content
                        return content
            except Exception:
                pass
        return None

    def _log_error_to_file(self, summary: str, exception: Exception | None=None):
        """
        Writes detailed error information to error.log in the current working directory.
        """
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                
        log_entry=[f"--- ERROR LOG ENTRY --- ({timestamp})", f"SUMMARY: {summary}"]
                
        if exception:
            log_entry.append(f"EXCEPTION TYPE: {type(exception).__name__}")
            log_entry.append(f"EXCEPTION DETAIL: {str(exception)}")
                        
            tb=traceback.format_exc()
            if "Traceback (most recent call last)" in tb and len(tb.strip()) > 50:
                log_entry.append("FULL TRACEBACK:\n" + tb)
            else:
                log_entry.append("No detailed Python traceback available from current context.")

        log_content="\n".join(log_entry) + "\n\n"
                
        try:
            with open(ERROR_LOG_FILE, 'a') as f:
                f.write(log_content)
            self.log_display.write(f"[STATUS] Detailed error logged to {ERROR_LOG_FILE.name}")
        except IOError as e:
            print(f"FATAL: Could not write to error.log: {e}")

    def _parse_tool_calls(self, response_text: str) -> list[tuple[str, dict]]:
        """
        Parses structured tool calls from the model's response using an XML-like tag.
        
        CRITICAL FIX: Added handling for HTML entities (&quot;, &amp;).
        """
                
        # Regex to find all <tool_call .../> tags
        tool_call_matches=re.findall(r'<tool_call\s+.*?\s*/>', response_text, re.DOTALL)
                
        extracted_tools=[]
                
        # Function to safely unescape the most common sequences
        def unescape_safe(s: str) -> str:
            """
            Replaces literal \n, \t, \r, \\ with actual characters,
            AND reverses common HTML entities used for quote/ampersand.
            """
            # 1. Reverse HTML entities (CRITICAL for Python code content)
            s=s.replace("&quot;", "\"")  # Replaces &quot; with "
            s=s.replace("&amp;", "&")    # Replaces &amp; with & (if model escapes it)

            # 2. Reverse Agent's backslash escaping (as defined in the prompt)
            return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").replace("\\\\", "\\")

        for match in tool_call_matches:
            # Find the function name
            func_match=re.search(r'function=["\'](write_file|run_code)["\']', match)
            if not func_match:
                continue
                        
            function_name=func_match.group(1)
            args={}
                        
            if function_name == "write_file":
                # Path and Content are required for write_file
                # Path is usually simple and less likely to contain internal quotes
                path_match=re.search(r'path=["\'](?P<path>[^"\']+)["\']', match)
                
                # --- CRITICAL REGEX FIX for 'content' ---
                # This regex captures everything after 'content=' until the final quote 
                # that immediately precedes the closing slash of the XML tag (with optional whitespace).
                # This makes it robust against internal quotes that are part of the file content.
                content_match=re.search(r'content=(?P<quote>["\'])(?P<content>.*?)(?P=quote)\s*/>', match, re.DOTALL)
                # ----------------------------------------
                        
                if path_match and content_match:
                    raw_path=path_match.group('path')
                    # Use the content group from the more robust regex
                    raw_content=content_match.group('content') 

                    try:
                        args['path']=unescape_safe(raw_path)
                        args['content']=unescape_safe(raw_content)
                        extracted_tools.append((function_name, args))
                        
                        # --- NEW LOGGING STATUS CHECK ---
                        if "\\n" in raw_content or "\\t" in raw_content:
                             self.log_display.write("[PARSER:STATUS] Successfully unescaped newline/tab characters in 'content' for `write_file`.")
                        # ---------------------------------------------

                    except Exception as e:
                        self.log_display.write(f"[PARSER:ERROR] Failed to unescape content/path for write_file: {e}")
                else:
                    self.log_display.write(f"[PARSER:WARN] Incomplete or unparseable write_file call: {match}")
                        
            elif function_name == "run_code":
                # Command is required for run_code
                # Command is the last argument, so we use the robust closing check
                command_match=re.search(r'command=(?P<quote>["\'])(?P<command>.*?)(?P=quote)\s*/>', match, re.DOTALL)
                
                if command_match:
                    raw_command=command_match.group('command')
                    try:
                        args['command']=unescape_safe(raw_command)
                        extracted_tools.append((function_name, args))
                    except Exception as e:
                        self.log_display.write(f"[PARSER:ERROR] Failed to unescape command for run_code: {e}")
                else:
                    self.log_display.write(f"[PARSER:WARN] Incomplete or unparseable run_code call: {match}")

        return extracted_tools

    # --- Textual Lifecycle Hooks ---

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
                
        with Container(id="app-grid"):
            yield Static(self._build_options_menu(), id="options-panel")
                    
            yield Container(
                self.log_display,
                Input(placeholder=self.sub_title, id="main-input"),
                id="main-content"
            )

        yield Footer()

    def on_mount(self) -> None:
        """Called after the application is mounted."""
        # Ensure the project directory exists
        TEMP_PROJECT_DIR.mkdir(parents=True, exist_ok=True)
                
        self.dark=True
        self.screen.styles.background="#1E1E1E"
        self.query_one(Header).styles.color="gold"

        self.log_display.write(f"[WELCOME] Own-CLI Agent V3.0 - Local LLM Agentic CLI\nMade by jnetai.com forum jnet.forumotion.com")
        self.log_display.write(f"[CONFIG] Project Directory: {TEMP_PROJECT_DIR.relative_to(Path.cwd())}")
        self.log_display.write(f"[CONFIG] Default Chat Model: {self.config.get_default_model('chat')}")
        self.log_display.write(f"[CONFIG] Default Agent Model: {self.config.get_default_model('agent')}")
        self.log_display.write(f"[STATUS] Ready. Use /agent /chat /model before your message.")
                
        # Load history into the input widget
        input_widget=self.query_one(Input)
        input_widget.history=self.command_history
        input_widget.focus()

        # --- NEW LINE HERE ---
        #start_mouse_listener(self)
    # --- Menu and Actions ---

    def _build_options_menu(self) -> str:
        """Generates the options menu content."""
        config_info=[
            f"--- Configuration ({CONFIG_FILE.name}) ---",
            f"Default Chat Model: {self.config.get_default_model('chat')}",
            f"Default Agent Model: {self.config.get_default_model('agent')}",
            "\n--- Providers ---"
        ]
                
        for p in self.config.config['providers']:
            status="[green]ENABLED[/green]" if p.get('enabled') else "[red]DISABLED[/red]"
            config_info.append(f"  [{status}] {p['name']} ({p['type']})")
            config_info.append(f"    Chat Model: {p.get('chat_model', 'N/A')}")
            config_info.append(f"    Agent Model: {p.get('agent_model', 'N/A')}")
            config_info.append(f"    Image Model: {p.get('image_model', 'N/A')}")

        permission_info=[
            "\n--- Permissions ---",
            f"File I/O: {'[green]ALLOWED[/green]' if self.permissions.is_allowed('allow_file_io') else '[red]BLOCKED[/red]'}",
            f"Code Execution: {'[green]ALLOWED[/green]' if self.permissions.is_allowed('allow_code_execution') else '[red]BLOCKED[/red]'}",
            f"Auto Browse: {'[green]ALLOWED[/green]' if self.permissions.is_allowed('allow_auto_browse') else '[red]BLOCKED[/red]'}",
            "\n[yellow]EDIT permissions.json TO CHANGE[/yellow]"
        ]

        return "\n".join(config_info + permission_info)


    def action_toggle_options(self) -> None:
        """An action to toggle the options panel display."""
        options_panel=self.query_one("#options-panel")
        options_panel.update(self._build_options_menu())
        # Toggle display property
        new_display="none" if options_panel.styles.display == "block" else "block"
        options_panel.styles.display=new_display
                
        app_grid=self.query_one("#app-grid")
                
        # Adjust grid columns based on display state
        if new_display == "block":
            app_grid.styles.grid_columns="2fr 8fr"
        else:
            app_grid.styles.grid_columns="0fr 10fr"


    def action_reset_session(self) -> None:
        """Resets the chat history and logs."""
        self.chat_history=[]
        self.log_display.clear()
        self.log_display.write("[STATUS] Session and chat history reset.")
        self.query_one(Input).value=""
        self.query_one(Input).placeholder=self.sub_title
        self.query_one(Input).focus()

    def action_show_tools(self) -> None:
        """Displays available tools in the log."""
        tools_info=[
            "[AVAILABLE TOOLS]",
            f"  [bold]run_code[/bold]: Executes shell commands. Requires 'allow_code_execution': {self.permissions.is_allowed('allow_code_execution')}",
            f"  [bold]write_file[/bold]: Writes content to the project folder. Requires 'allow_file_io': {self.permissions.is_allowed('allow_file_io')}",
            "[STATUS] Use /agent to enable tool calling mode."
        ]
        self.log_display.write("\n".join(tools_info))

    # --- NEW MODEL HELPER ---
    def _get_current_model(self, mode: str) -> str:
        """Helper to get the model, checking the temporary override first."""
        if self.temp_model_override:
            return self.temp_model_override
        elif mode == 'agent':
            return self.config.get_default_model('agent')
        else: # chat mode
            return self.config.get_default_model('chat')

    # --- NEW COMMAND PROCESSOR ---
    def action_process_command(self, user_input: str) -> None:
        """Processes user input, checking for special commands (/chat, /agent, /model)."""
        
        parts=user_input.strip().split(maxsplit=1)
        command=parts[0].lower()
        prompt=parts[1].strip() if len(parts) > 1 else ""

        # 1. Handle /model command (NEW)
        if command == "/model":
            if not prompt:
                current=self.temp_model_override if self.temp_model_override else "default (from config)"
                self.log_display.write(f"Current temporary model: [bold]{current}[/bold]. Usage: /model <model-name> or /model reset")
                return

            model_name=prompt
            if model_name in ("reset", "clear", "default"):
                self.temp_model_override=None
                self.log_display.write("Model override cleared. Reverting to default configuration.")
            else:
                self.temp_model_override=model_name
                self.log_display.write(f"Temporary model switched to: [bold cyan]{model_name}[/bold cyan] for both chat and agent modes.")
            
            # Update placeholder immediately
            self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {self._get_current_model(self.session_mode)})"
            return
            
        # 2. Handle /chat and /agent
        if command == "/chat":
            self.session_mode='chat'
            # /chat without prompt just switches mode
            if not prompt:
                # Load personality if exists
                personality = self._load_personality()
                if personality:
                    self.log_display.write(f"[CHAT] Switched to chat mode. Loaded personality from personality.txt")
                else:
                    self.log_display.write(f"[CHAT] Switched to chat mode (no personality.txt found)")
                self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {self._get_current_model(self.session_mode)})"
                self.query_one(Input).focus()
                return
        elif command == "/agent":
            self.session_mode='agent'
        
        # Determine the final prompt and mode
        if command.startswith("/") and command not in ["/chat", "/agent"]:
            # Treat unknown command as part of the prompt in the current mode
            mode_to_use=self.session_mode
            prompt_to_use=user_input
        else:
            mode_to_use=self.session_mode
            prompt_to_use=prompt

        if not prompt_to_use:
            self.log_display.write(f"[STATUS] Please provide a prompt after the command: /{command}.")
            return
            
        # 3. Determine the model to use
        model_to_use=self._get_current_model(mode_to_use)
            
        # 4. Execute based on mode
        if mode_to_use == 'chat':
            self._handle_chat_query(model_to_use, prompt_to_use)
        elif mode_to_use == 'agent':
            self._handle_agent_query(model_to_use, prompt_to_use)
            
        # Update placeholder at the end
        self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {model_to_use})"
        self.query_one(Input).focus()

    # --- Input Handling and Core Agent Logic ---
    
    def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission from the user."""
        user_input=message.value.strip()
        self.query_one(Input).value="" # Clear input immediately
                
        if not user_input:
            return

        self.log_display.write(f"[YOU] {user_input}")

        # DETECT FILE READ: Store file content when user says "read X.md"
        if user_input.lower().startswith("read ") or "read" in user_input.lower():
            # Try to extract filename
            import re
            match = re.search(r'read\s+([^\s]+\.md)', user_input, re.IGNORECASE)
            if match:
                filename = match.group(1)
                self.last_read_file = filename
                # Try to read and store summary
                try:
                    with open(filename, 'r') as f:
                        content = f.read()
                        # Store summary (first 500 chars)
                        self.file_memory[filename] = content[:500] + "..." if len(content) > 500 else content
                    self.log_display.write(f"[MEMORY] Stored: {filename} ({len(content)} chars)")
                except FileNotFoundError:
                    self.log_display.write(f"[MEMORY] File not found: {filename}")

        # Add command to history list
        if user_input not in self.command_history:
            self.command_history.append(user_input)
            self._save_history()

        # --- UPDATED: Use the new command processor for all command logic ---
        self.action_process_command(user_input)
        # --- End of update ---

# --- Autocomplete Suggestions for Textual Input ---
    def on_input_changed(self, event: Input.Changed) -> None:
        """
        Handles input changes to provide dynamic autocompletion suggestions 
        for commands and model names.
        """
        user_input=event.value
        suggestions=[]
        input_widget=self.query_one(Input)
        
        if user_input.startswith("/"):
            
            if user_input.startswith("/model"):
                # Split the input. Result will be ['/model', 'fragment'] or ['/model']
                parts=user_input.split(maxsplit=1)
                
                # CRITICAL FIX: Check if the 'fragment' part exists (i.e., if parts length > 1)
                # If the input is just '/model' or '/model ' (as in the crash), parts[1] doesn't exist.
                typed_fragment=parts[1] if len(parts) > 1 else ""
                
                # Assumes ModelManager.get_ollama_models() is implemented 
                # to return a list of local models (e.g., from 'ollama ls')
                models=self.model_manager.get_ollama_models() 
                
                # Include the 'reset' command
                all_model_options=["reset"] + models
                
                suggestions=[
                    option
                    for option in all_model_options
                    if option.startswith(typed_fragment)
                ]
                # Format suggestions to include the full command for the user
                input_widget.suggestions=[f"/model {s}" for s in suggestions]

            else:
                # Basic command completion (/chat, /agent)
                all_commands=["/chat", "/agent", "/model"]
                suggestions=[cmd for cmd in all_commands if cmd.startswith(user_input.lower())]
                input_widget.suggestions=suggestions
                
        else:
            # Clear suggestions when not typing a command
            input_widget.suggestions=[]


    def _handle_chat_query(self, model_name: str, prompt: str):
        """Processes a query in simple chat mode (no tools)."""
        # Ensure personality is loaded
        if not self.chat_personality:
            self._load_personality()
        
        # Check if user is asking about a previously read file
        if self.last_read_file and any(word in prompt.lower() for word in ['it', 'that', 'this file', 'the file']):
            prompt = f"Context: The last file I read was '{self.last_read_file}'. Summary: {self.file_memory.get(self.last_read_file, 'N/A')}\n\nQuestion: {prompt}"
        
        # Check if this is a follow-up about previous requirements
        if self.last_requirements and any(word in prompt.lower() for word in ['continue', 'same', 'previous', 'again', 'that project', 'the game']):
            prompt = f"Context: Previous project requirements: {self.last_requirements}\n\nUser wants to continue/follow-up: {prompt}"
        
        # Build messages with personality
        messages = []
        
        # Add personality as system message if exists
        if self.chat_personality:
            messages.append({"role": "system", "content": self.chat_personality})
        
        # Add recent chat history
        messages.extend(self.chat_history[-5:])
        messages.append({"role": "user", "content": prompt})
        
        response_text=self.model_manager.call_model(model_name, messages, mode='chat')
                
        if not response_text.startswith("ERROR"):
            # Remove thinking tags if present
            if '<think>' in response_text:
                response_text = re.sub(r"</think>.*?</think>", "", response_text, flags=re.DOTALL).strip()
                        
            self.chat_history.append({"role": "assistant", "content": response_text})
            self.log_display.write(f"[ASSISTANT] {response_text}")
            
            # Run TTS in background thread after displaying text (only if enabled in config)
            if self.config.config.get('tts_enabled', False):
                def run_tts():
                    try:
                        from utils import speak_response
                        speak_response(response_text)
                    except Exception:
                        pass
                
                import threading
                tts_thread=threading.Thread(target=run_tts, daemon=True)
                tts_thread.start()

        # Ensure the input placeholder reflects the chat's current model
        current_model=self._get_current_model(self.session_mode)
        self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {current_model})"


    def _handle_agent_query(self, model_name: str, prompt: str):
        """Processes a query in agentic (tool-using) mode with planning and checklist."""
        # Store requirements for follow-up questions
        self.last_requirements = prompt
        self.log_display.write("[AGENT:INFO] Starting agent cycle...")
        
        # Initialize planning/checklist for new task
        self.current_project_name=self._extract_project_name(prompt)
        self.project_subfolder=self._create_project_subfolder(self.current_project_name)
        self.checklist=self._init_checklist(prompt)
        self.iteration_count=0
        self.last_error=None
        
        # Update tool executor to use project subfolder
        self.tool_executor.set_project_dir(self.project_subfolder)
        
        self.log_display.write(f"[PROJECT] Working in: {self.project_subfolder.name}")
        self.log_display.write(f"[CHECKLIST] Initialized {len(self.checklist)} tasks")
        self.log_display.write(f"[REQUIREMENTS] {prompt[:100]}...")

        # 1. Check if clarification is needed (Planning Mode)
        if self._needs_planning(prompt):
            self.log_display.write("[PLANNING] Request needs clarification. Asking questions...")
            clarification_prompt=self._generate_clarification_prompt(prompt)
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Ask clarifying questions to understand the user's needs better. Keep questions brief and focused."},
                {"role": "user", "content": clarification_prompt}
            ]
            response=self.model_manager.call_model(model_name, messages, mode='chat')
            self.log_display.write(f"[PLANNING] {response}")
            self.log_display.write("[PLANNING] Please answer the above questions, then re-submit your request.")
            return

        # 2. REQUIREMENT CONFIRMATION: Summarize what we understood and confirm
        requirements_summary = self._summarize_requirements(prompt)
        self.log_display.write(f"[CONFIRM] I understood: {requirements_summary}")
        self.log_display.write("[CONFIRM] Starting work... (If incorrect, reset with Ctrl+R and rephrase)")

        # 2. Build system prompt with checklist
        system_prompt=self._build_agent_system_prompt()

        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        # 3. Start execution loop (with checklist validation)
        for step in range(1, self.MAX_AGENT_STEPS + 1):
            self.iteration_count=step
            self.log_display.write(f"[AGENT:STEP {step}/{self.max_iterations}] Reasoning and calling model...")
            
            response_text=self.model_manager.call_model(model_name, messages, mode='agent')

            if response_text.startswith("ERROR"):
                self.log_display.write(f"[AGENT:ERROR] Model call failed: {response_text}")
                break

            messages.append({"role": "assistant", "content": response_text})

            tool_calls=self._parse_tool_calls(response_text)

            if not tool_calls:
                final_answer=re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
                
                # Check if checklist is complete before accepting
                if not self._check_all_completed():
                    self.log_display.write(f"[CHECKLIST] Incomplete! Missing: {self._get_incomplete_tasks()}")
                    messages.append({"role": "user", "content": f"Your answer indicates completion but checklist shows: {self._get_incomplete_tasks()}. Please verify and complete all tasks."})
                    continue
                
                with open("last.txt", "w", encoding="utf-8") as f:
                    f.write(final_answer)
                self.log_display.write("[STATUS] Response put into last.txt ✅")
                self.log_display.write(f"[ASSISTANT] {final_answer}")
                self.log_display.write("[SUCCESS] All checklist items completed! ✅")
                break
            else:
                function_name, args=tool_calls[0]
                self.log_display.write(f"[AGENT:TOOL CALL] {function_name}")
                
                tool_output=""
                if function_name == "write_file":
                    tool_output=self.tool_executor.write_file(**args)
                elif function_name == "run_code":
                    tool_output=self.tool_executor.run_code(**args)
                    
                if "ERROR" in tool_output:
                    self.last_error=tool_output
                    self.log_display.write(f"[ERROR] {tool_output[:100]}")
                else:
                    self.last_error=None
                
                self._update_checklist_from_output(function_name, tool_output)
                
                messages.append({"role": "tool", "content": tool_output})
                self.log_display.write(f"[AGENT:TOOL OUTPUT] {tool_output[:150]}...")

                if self.last_error and self.iteration_count < self.max_iterations:
                    messages.append({"role": "user", "content": f"Error detected: {self.last_error}. Fix the issue and continue. Checklist: {self._get_incomplete_tasks()}"})

            if self.iteration_count >= self.max_iterations:
                self.log_display.write(f"[AGENT:WARN] Max iterations ({self.max_iterations}) reached.")
                break
                
        current_model=self._get_current_model(self.session_mode)
        self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {current_model})"
        self.query_one(Input).focus()

    # --- Helper methods for planning/checklist ---

    def _extract_project_name(self, prompt: str) -> str:
        """Extract project name from prompt."""
        prompt_lower=prompt.lower()
        if 'tetris' in prompt_lower: return 'tetris'
        if 'game' in prompt_lower: return 'game'
        if 'web' in prompt_lower or 'html' in prompt_lower: return 'webapp'
        if 'python' in prompt_lower or 'script' in prompt_lower: return 'script'
        return 'project'

    def _needs_planning(self, prompt: str) -> bool:
        """Determine if clarification questions are truly needed."""
        prompt_lower=prompt.lower()
        
        # Check for explicit language/tech specifications
        has_lang=any(x in prompt_lower for x in ['python', 'html', 'javascript', 'css', 'js', 'game', 'web', 'cli', 'app', 'tetris', 'script', 'c++', 'rust', 'go '])
        has_goal=any(x in prompt_lower for x in ['make', 'create', 'build', 'write', 'develop', 'implement', 'game', 'app', 'program'])
        
        # Only ask if truly vague - no language AND no clear goal
        if not has_lang and not has_goal:
            return True
        
        # If they mention something specific like "make a tetris game" or "build a web app", proceed without asking
        return False

    def _generate_clarification_prompt(self, prompt: str) -> str:
        """Generate clarification questions that include the original context."""
        return f"""The user wants to build something but the request needs clarification.

ORIGINAL REQUEST: "{prompt}"

Based on this request, ask ONE brief clarifying question to determine the specific technology/language they want to use, or what exactly they want to build.

Examples:
- "What programming language would you like to use?"
- "What specific type of application is this?"
- "Should this be a web app, desktop app, or CLI tool?"

Ask just ONE focused question."""

    def _summarize_requirements(self, prompt: str) -> str:
        """Extract and summarize key requirements from the prompt to confirm understanding."""
        prompt_lower = prompt.lower()
        
        # Extract game type
        game_type = "unknown"
        if 'tetris' in prompt_lower:
            game_type = "Tetris"
        elif 'street fighter' in prompt_lower or 'fighter' in prompt_lower:
            game_type = "Street Fighter-style fighting game"
        elif 'space shooter' in prompt_lower or 'shooter' in prompt_lower:
            game_type = "Space shooter"
        elif 'platformer' in prompt_lower:
            game_type = "Platformer"
        
        # Extract language/tech
        tech = "Python (default)"
        if 'html' in prompt_lower or 'web' in prompt_lower:
            tech = "HTML/CSS/JavaScript"
        elif 'javascript' in prompt_lower or 'js' in prompt_lower:
            tech = "JavaScript"
        
        # Extract platform
        platform = "CLI"
        if 'web' in prompt_lower:
            platform = "Web browser"
        elif 'mobile' in prompt_lower:
            platform = "Mobile"
        
        return f"{game_type} game in {tech} for {platform}"

    def _build_agent_system_prompt(self) -> str:
        """Build the system prompt with checklist requirements and personality."""
        checklist_text="\n".join([f"- {item['task']}: {item['description']}" for item in self.checklist])
        
        # Add personality if loaded
        personality_section = ""
        if self.chat_personality:
            personality_section = f"\nPERSONALITY:\n{self.chat_personality}\n"
        
        return f"""You are an expert CLI agent. Your goal is to satisfy the user's request using tools.

{personality_section}
You MUST use a checklist to track progress. Update it as you complete tasks:

{checklist_text}

STRICT RULES:
1. **TOOL USAGE:** Output ONLY one self-closing XML tag per turn: <tool_call function="TOOL_NAME" arg1="value"/>
2. **ESCAPING:** Use \\\\n for newlines, \\\\t for tabs in content.
3. **AVAILABLE TOOLS:**
   - write_file(path, content): Write code files
   - run_code(command): Execute shell commands
4. **CODE OUTPUT:** All output must use print() statements
5. **ERROR HANDLING:** If run_code returns ERROR, fix and retry - don't give up!
6. **ITERATION:** Keep running tests until the code WORKS. Do not declare success until verified.
7. **CHECKLIST:** Mark tasks complete only after actually verified working.
8. **PROJECT FOLDER:** Write all files to the current directory (already set to project folder).
9. **AUTONOMY:** Never ask for permission. Persist until all checklist items done."""

    def _update_checklist_from_output(self, tool: str, output: str) -> None:
        """Update checklist based on ACTUAL tool execution results - more reliable."""
        
        # Check for actual success (not just keyword in error message)
        is_success = "SUCCESS" in output and "ERROR" not in output
        is_error = "ERROR" in output or output.startswith("Error")
        
        if tool == "write_file":
            if is_success:
                self._update_checklist("Create project structure", True)
                
                # More reliable: check actual file existence
                if self.project_subfolder:
                    files = list(self.project_subfolder.iterdir())
                    for f in files:
                        if f.suffix == ".py":
                            self._update_checklist("Write Python code", True)
                        elif f.suffix == ".html":
                            self._update_checklist("Create HTML file", True)
                        elif f.suffix == ".css":
                            self._update_checklist("Create CSS styles", True)
                        elif f.suffix == ".js":
                            self._update_checklist("Create JavaScript", True)
            elif is_error:
                # Mark structure as incomplete if write failed
                self._update_checklist("Create project structure", False)
                
        elif tool == "run_code":
            if is_success:
                # Only mark tests complete if we actually ran something
                self._update_checklist("Test Python code", True)
                self._update_checklist("Test game runs", True)
                self._update_checklist("Final validation", True)
            elif is_error:
                # Don't mark complete if error occurred
                pass
        
        # Always verify files exist
        if self.project_subfolder and any(self.project_subfolder.iterdir()):
            self._update_checklist("Verify all files exist", True)
