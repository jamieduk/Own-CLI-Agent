#!/bin/bash
# (c) J~Net 2025
#
sudo chmod +x *.sh

echo "Setting Up Own-CLI AI Agent & Ollama"
# 1. Create venv only if the folder does not exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
    echo "Virtual Environment Created."
fi

# 2. Activate venv only if not already active
# $VIRTUAL_ENV is set by the 'source venv/bin/activate' script
if [ -z "$VIRTUAL_ENV" ] || [ "$(basename "$VIRTUAL_ENV")" != "venv" ]; then
    source venv/bin/activate
    echo "Virtual Environment Activated."
else
    echo "Virtual Environment already active."
fi

# Install required pip things!
pip install textual requests

echo "Looking For Ollama..."


if [ -f "/usr/local/bin/ollama" ]; then
    # Ollama is present
    echo "Ollama is installed."
else
    # Ollama is not present
    echo "Installing Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "Getting Ollama Models"
ollama pull llama3.1:8b
ollama pull deepseek-r1:7b
ollama pull llava-phi3:latest

echo "Setup Complete"
echo ""
echo "Use ./start.sh to start"
echo "Read Notes.txt And README.md files to learn how to configure and customise!"


bash ./start.sh






