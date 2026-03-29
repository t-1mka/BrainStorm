#!/bin/bash
# BrainStorm — запуск на Linux/macOS
# Использование: chmod +x start.sh && ./start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  +---------------------------------+"
echo "  |  BrainStorm -- Zapusk servera   |"
echo "  +---------------------------------+"
echo ""

# Проверяем Python
if ! command -v python3 &>/dev/null; then
    echo "  [OSHIBKA] python3 ne nayden!"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  macOS: brew install python3"
    exit 1
fi

PYVER=$(python3 -c "import sys; print(sys.version_info >= (3,10))")
if [ "$PYVER" != "True" ]; then
    echo "  [OSHIBKA] Nuzhen Python 3.10+"
    exit 1
fi

# Создаём venv
if [ ! -d "venv" ]; then
    echo "  Sozdayu virtualnoe okruzhenie..."
    python3 -m venv venv
fi

# Активируем
source venv/bin/activate

echo "  Zapusk..."
echo ""
python run.py
