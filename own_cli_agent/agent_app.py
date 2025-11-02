import json
import os
import time
import re
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, RichLog
from textual.containers import Container
from textual.binding import Binding

# Relative imports from the new structure
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
    ]

    MAX_AGENT_STEPS=3000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config=ConfigManager()
        self.permissions=PermissionsManager()
        self.app_title="Own-CLI Agent (Ollama/Multi-Provider)"
        self.sub_title="Enter a goal or a message. Use /agent  /chat  /model"
        self.log_display=RichLog(id="log-display", highlight=True, markup=True)
        
        self.command_history=self._load_history()
        
        # Pass self (the App instance) to managers for error logging access
        self.model_manager=ModelManager(self.config, self.log_display, self)
        self.tool_executor=ToolExecutor(self.permissions, self.log_display, self)
        self.chat_history=[]
        self.session_mode='agent' # Default mode: agent
        
        # --- NEW: Temporary model override state ---
        self.temp_model_override: str | None=None

    # --- Utility Methods ---

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

        self.log_display.write(f"[WELCOME] Own-CLI Agent V2.0 - Local LLM Agentic CLI\nMade by jnetai.com forum jnet.forumotion.com")
        self.log_display.write(f"[CONFIG] Project Directory: {TEMP_PROJECT_DIR.relative_to(Path.cwd())}")
        self.log_display.write(f"[CONFIG] Default Chat Model: {self.config.get_default_model('chat')}")
        self.log_display.write(f"[CONFIG] Default Agent Model: {self.config.get_default_model('agent')}")
        self.log_display.write(f"[STATUS] Ready. Use /agent or /chat before your message.")
                
        # Load history into the input widget
        input_widget=self.query_one(Input)
        input_widget.history=self.command_history
        input_widget.focus()

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
        hide_think=True
                
        self.chat_history.append({"role": "user", "content": prompt})
                
        # Limit context to the last 5 messages for simple chat
        context_messages=self.chat_history[-5:]
                
        response_text=self.model_manager.call_model(model_name, context_messages, mode='chat')
                
        if not response_text.startswith("ERROR"):
            # Conditionally strip the <think> tags
            if hide_think:
                response_text=re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
                        
            self.chat_history.append({"role": "assistant", "content": response_text})
            self.log_display.write(f"[ASSISTANT] {response_text}")
        else:
            self.log_display.write(f"[ERROR] Chat failed: {response_text}")

        # Ensure the input placeholder reflects the chat's current model
        current_model=self._get_current_model(self.session_mode)
        self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {current_model})"


    def _handle_agent_query(self, model_name: str, prompt: str):
        """Processes a query in agentic (tool-using) mode."""
        self.log_display.write("[AGENT:INFO] Starting agent cycle...")

        # 1. Initialize messages with a robust system prompt
        system_prompt=(
            "You are an expert CLI agent. Your goal is to satisfy the user's request using tools. "
            "You MUST strictly adhere to the following rules:\n\n"
            "1. **TOOL USAGE (CRITICAL):** Output ONLY ONE single, self-closing XML tag per turn. "
            "   It MUST be in the form: <tool_call function=\"TOOL_NAME\" ARG1=\"value\" ARG2=\"value\"/>. "
            "   **NEVER** use separate opening and closing tags (e.g., `<tool_call>...</tool_call>`).\n"
            "2. **ESCAPING (CRITICAL):** Arguments MUST use double quotes. For `write_file` content, "
            "   use **literal backslash sequences**:\n"
            "   - **Newline (`\\n`)** MUST be `\\\\n`.\n"
            "   - **Tab (`\\t`)** MUST be `\\\\t`.\n"
            "3. **AVAILABLE TOOLS:**\n"
            "   - [bold]write_file[/bold](path, content): Writes Python/script code. Content **must** be escaped and provided as a single attribute value.\n"
            "   - [bold]run_code[/bold](command): Executes shell commands (e.g., `python file.py`).\n"
            
            # --- CRITICALLY UPDATED CODE OUTPUT MANDATE ---
            "4. **CODE OUTPUT MANDATE (CRITICAL):** All code that returns a value intended for the user MUST be wrapped in an explicit `print()` call to ensure the output is written to STDOUT (e.g., `print(function_name())`). If the code doesn't output to STDOUT, the agent fails.\n"
            
            "5. **DEBUG MANDATE (CRITICAL):** Treat any `TOOL:ERROR`, `PARSER:ERROR`, or **EMPTY/WHITESPACE-ONLY** output from `run_code` as a failure. Your immediate next step **MUST** be to rewrite the file to correct the logic (e.g., adding the missing `print()`). **DO NOT** attempt to justify or declare success when the output is empty.\n"
            "6. **AUTONOMY:** Do not ask for human permission. Persist until the mission is validated and fully completed. Stop only with a final, non-tool answer."
        )

        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        # 2. Start execution loop (max MAX_AGENT_STEPS)
        for step in range(1, self.MAX_AGENT_STEPS + 1):
            self.log_display.write(f"[AGENT:STEP {step}] Reasoning and calling model...")
            
            # Get response from model
            response_text=self.model_manager.call_model(model_name, messages, mode='agent')

            if response_text.startswith("ERROR"):
                self.log_display.write(f"[AGENT:ERROR] Model call failed: {response_text}")
                break

            # Add model's thought/response to history
            messages.append({"role": "assistant", "content": response_text})

            # 3. Parse and Execute Tools
            tool_calls=self._parse_tool_calls(response_text)

            if not tool_calls:
                # No tool call found - this is the final answer
                final_answer=re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
                self.log_display.write(f"[ASSISTANT] {final_answer}")
                break # Exit the loop after providing the final answer

            # If tool calls are present, execute the first one
            function_name, args=tool_calls[0]
            self.log_display.write(f"[AGENT:TOOL CALL] {function_name} with args: {', '.join(f'{k}=...' for k in args.keys())}")
            
            tool_output=""
            if function_name == "write_file":
                tool_output=self.tool_executor.write_file(**args)
            elif function_name == "run_code":
                tool_output=self.tool_executor.run_code(**args)
                
            # 4. Add tool output back to the conversation for the next step
            messages.append({"role": "tool", "content": tool_output})
            self.log_display.write(f"[AGENT:TOOL OUTPUT] {tool_output.splitlines()[0]}...") # Log the first line of the output for conciseness

            # 5. Check for Max Steps
            if step == self.MAX_AGENT_STEPS:
                self.log_display.write(f"[AGENT:WARN] Maximum steps ({self.MAX_AGENT_STEPS}) reached. Terminating.")
                messages.append({"role": "tool", "content": f"AGENT:WARN: Maximum steps ({self.MAX_AGENT_STEPS}) reached. Provide a final summary of progress."})
                # Re-call the model one last time to get a summary response (final answer mode)
                response_text=self.model_manager.call_model(model_name, messages, mode='agent')
                final_answer=re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
                self.log_display.write(f"[ASSISTANT] {final_answer}")
                break
                
        # Ensure the input placeholder reflects the agent's current mode
        current_model=self._get_current_model(self.session_mode)
        self.query_one(Input).placeholder=f"Current Mode: /{self.session_mode} (Model: {current_model})"
        self.query_one(Input).focus()
