#!/bin/bash
# (c) J~Net 2025
#

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

echo "Virtual Environment Setup and ready!"
echo ""
echo "Starting Own-Agent-AI..."
echo ""
#./venv/bin/python own_cli.py
./venv/bin/python -m own_cli_agent.main
