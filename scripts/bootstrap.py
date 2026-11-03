"""Create local secrets once. Does not install software or start services."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / ".env"
if target.exists():
    print("Existing .env preserved.")
else:
    text = (ROOT / ".env.example").read_text()
    text = text.replace("replace-with-a-long-random-value", secrets.token_urlsafe(36))
    text += f"\nN8N_ENCRYPTION_KEY={secrets.token_hex(32)}\n"
    text += "N8N_IMAGE=docker.n8n.io/n8nio/n8n:2.46.4\n"
    text += "OLLAMA_IMAGE=ollama/ollama:0.40.14\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)
    print("Created private .env. No secrets printed. Local model calls are disabled by default.")
