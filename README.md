# Own-CLI Agent (Ollama/Multi-Provider)

A powerful, self-contained, and self-correcting CLI Agent built with Python and [Textual TUI](https://textual.textualize.io/). This agent is designed to interface with local or remote Large Language Models (LLMs)—such as those running via Ollama—and execute complex, multi-step tasks by utilizing file I/O and shell code execution with robust error handling.

## ✨ Features

* **Terminal User Interface (TUI):** A rich, interactive interface built with Textual for a better user experience than a standard console.
* **Agentic Workflow:** Supports multi-step reasoning, tool-calling (write file, run code), and iterative self-correction based on tool output.
* **Multi-Provider Support:** Designed to handle configuration for various LLM providers (e.g., Ollama, OpenAI, etc.).
* **Secure Execution:** Uses a `PermissionsManager` to control access to sensitive operations like file I/O and code execution.
* **Robust Parsing:** Custom, highly resilient tool-call parsing logic that handles complex multi-line code, escaping (`\\n`), and HTML entity (`&quot;`) issues.

## 🚀 Getting Started

### Prerequisites

1.  **Python 3.10+**
2.  **Ollama (Optional but Recommended):** For running local models like Llama 3.1.
3.  **Virtual Environment:** Highly recommended for dependency management.

### Installation

1.  **Clone the repository (or set up the project structure):**
    ```bash
    git clone [your-repo-link]
    cd project_folder 
    # NOTE: The actual application structure is assumed to be `project_folder` containing the modules.
    ```

2.  **Install dependencies:**
    *(Assuming dependencies are handled by `model_manager`, `tool_executor`, and Textual.)*
    ```bash
    # Install Textual and other libraries used in the code
    pip install textual # And any other required packages like the model API clients
    ```

### 🏃 Running the Application

For Python files longer than 200 lines (as this one likely is, given its complexity), a robust bash script is the recommended method to ensure a fast, consistent launch experience with a dedicated virtual environment.

We recommend using the following bash script to start the application:

**`start.sh` (Recommended Launch Method)**
```bash
#!/bin/bash

# Define the virtual environment directory
VENV_DIR=".venv"

# 1. Create and activate the virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Install dependencies (adjust as necessary)
    echo "Installing dependencies..."
    pip install textual # Add your other required packages here
else
    source "$VENV_DIR/bin/activate"
fi

echo "Starting Own-CLI Agent..."
# Run the main module
python -m agent_test 

# Note: The application is run as a module (`-m`) which correctly handles relative imports (`from .config import...`).
To run the agent:Bashchmod +x start.sh
./start.sh
💻 Usage and CommandsThe agent starts in the TUI, with all interaction taking place in the main input box.ModesThe agent supports two primary modes, which can be specified using a prefix or set as the session default.PrefixMode NameDescription/chatChat ModeSimple question/answer. No tools are used, and the conversation is focused on direct answers./agentAgent ModeGoal-driven. The agent will use available tools (write_file, run_code) and multiple steps to achieve the objective. (Default Mode)TUI Bindings (Keyboard Shortcuts)Key BindingActionDescriptionCtrl+Otoggle_optionsToggles the Configuration/Permissions side panel.Ctrl+QquitExits the application.Ctrl+Rreset_sessionClears the chat history and resets the session mode to default.Ctrl+Dshow_toolsDisplays a list of available tools and their permission status.⚙️ ConfigurationConfiguration is managed via external JSON files in the project directory:FilePurposeDescriptionconfig.jsonModel/Provider ConfigDefines LLM providers (e.g., Ollama endpoints, API keys), default models for chat and agent modes.permissions.jsonSecurityControls dangerous operations like allow_file_io and allow_code_execution. Set these carefully!history.jsonHistoryStores the last 50 unique commands entered by the user.error.logDebuggingDetailed Python tracebacks and error summaries are written here../project_folderWorkspaceAll files created by the agent (write_file tool) are contained within this directory.
