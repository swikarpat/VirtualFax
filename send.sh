#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. Validate Arguments
if [ -z "$1" ]; then
  echo "Usage: ./send.sh <PHONE_NUMBER> [RECIPIENT_NAME] [FILE_NAMES...]"
  echo "Example: ./send.sh 510-272-6982 'Alameda County' application.pdf"
  echo "         ./send.sh 510-272-6982 'Alameda County' (auto-detects newest in outbox/)"
  exit 1
fi

PHONE="$1"
RECIPIENT="${2:-Recipient}"

# 2. Pick Files (Specified or Auto-detect from outbox/)
if [ -n "$3" ]; then
  shift 2
  FILES=()
  for f in "$@"; do
    if [ ! -f "$f" ] && [ -f "outbox/$f" ]; then
      FILES+=("outbox/$f")
    else
      FILES+=("$f")
    fi
  done
else
  # Grab the most recent PDF from outbox/
  FILE=$(ls -t outbox/*.pdf 2>/dev/null | head -n 1)
  if [ -z "$FILE" ]; then
    echo "Error: No PDF files found in outbox/ folder."
    exit 1
  fi
  echo "Auto-detected newest document: $FILE"
  FILES=("$FILE")
fi

# 3. Execute
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

./faxctl remote-send "$PHONE" "${FILES[@]}" --recipient-name "$RECIPIENT"
