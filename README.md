# Own-CLI Agent (Ollama/Multi-Provider)

A powerful, self-contained, and **self-correcting CLI Agent** built with Python and [Textual TUI](https://textual.textualize.io/). This agent is designed to interface with local or remote Large Language Models (LLMs)—such as those running via Ollama—and execute complex, multi-step tasks by utilizing file I/O and shell code execution with robust error handling.

***

## ✨ Features

* **Terminal User Interface (TUI):** A rich, interactive interface built with **Textual** for a better user experience than a standard console.
* **Agentic Workflow:** Supports multi-step reasoning, tool-calling (`write_file`, `run_code`), and **iterative self-correction** based on tool output.
* **Multi-Provider Support:** Designed to handle configuration for various LLM providers (e.g., Ollama, OpenAI, etc.).
* **Secure Execution:** Uses a `PermissionsManager` to control access to sensitive operations like file I/O and code execution.
* **Robust Parsing:** Custom, highly resilient tool-call parsing logic that handles complex multi-line code, escaping (`\\n`), and HTML entity (`&quot;`) issues.

***

## 🚀 Getting Started

**Own-CLI-Agent By J~Net 2025**

**Repository:** `https://github.com/jamieduk/Own-CLI-Agent`

### Prerequisites

1.  **Python 3.10+**
2.  **Ollama (Optional but Recommended):** For running local models like Llama 3.1.
3.  **Virtual Environment:** Highly recommended for dependency management.

### Installation & Launch (Auto Setup)

Use the provided shell scripts for a quick setup and launch:

```bash
# Set permissions and run the setup script
sudo chmod +x *.sh && ./setup.sh

# Launch the application
./start.sh
Note: For large Python applications (over 200 lines), starting with a bash script that sets up a virtual environment and runs the module (python -m ...) is recommended, as it makes these big Python apps run super fast.💻 Usage and CommandsThe agent starts in the TUI, with all interaction taking place in the main input box.ModesThe agent supports two primary modes, which can be specified using a prefix or set as the session default.PrefixMode NameDescription/chatChat ModeSimple question/answer. No tools are used, and the conversation is focused on direct answers./agentAgent ModeGoal-driven. The agent will use available tools (write_file, run_code) and multiple steps to achieve the objective. (Default Mode)💡 
Example Prompts/chat tell me a bad joke

/agent Create a Python file named 'agent_test.py' that defines a function called 'greeting' which returns the string "Agent mode works!". Then, use the 'run_code' tool to execute that file using 'python agent_test.py' and print the output
TUI Bindings (Keyboard Shortcuts)Key BindingActionDescriptionF1 or Ctrl+Otoggle_optionsToggles the Configuration/Permissions side panel.Ctrl+QquitExits the application.Ctrl+Rreset_sessionClears the chat history and resets the session mode to default.Ctrl+Dshow_toolsDisplays a list of available tools and their permission status.
Copy/Paste and LinksLinks: Hold the Ctrl button and click links to open them in your browser.Selection: Hold Shift to select and copy/paste text with the mouse or keyboard (Ctrl+C/Ctrl+V).⚙️ ConfigurationConfiguration files are stored in your home directory 
for persistent settings.FilePurposeManagement Commandconfig.jsonModel/Provider Config

gedit ~/.own_cli_agent/config.json
permissions.json
Security/Tool Access
gedit ~/.own_cli_agent/permissions.jsonhistory.json
User Command History(Managed automatically)error.log

Debugging Logs(Managed automatically)Configuration TipsEdit the config: gedit ~/.own_cli_agent/config.jsonCheck 

Permissions: gedit ~/.own_cli_agent/permissions.json

Backup a config: 
cp ~/.own_cli_agent/config.json .

WorkspaceDirectoryPurpose./project_folder

The default working directory. 
All files created by the agent (write_file tool) are contained within this folder.
