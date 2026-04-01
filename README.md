# AI File Organizer v2.0

AI-powered file organization tool. Analyzes your files, assigns tags and categories, and builds a clean directory structure.

## Quick Start (Windows)

1. Double-click **START.bat**
2. Browser opens at `http://localhost:8765`

Or manually:
```
pip install flask flask-cors requests
python server.py
```

---

## Features

| Feature | Details |
|---|---|
| **File Explorer** | Browse directories, **Select All** checkbox, filter by name/type |
| **AI Analysis** | Analyzes filename + metadata via AI — no file access errors |
| **3 Tags per file** | AI assigns exactly 3 descriptive tags for every file |
| **System Prompt Preview** | See/edit the exact prompt sent to AI before running |
| **Organize & Move** | Copy or Move, auto-loads from analysis results |
| **Select All** | Master checkbox on Explorer, Queue, and Organize panels |
| **Log Filter** | Filter log by type (Info/Success/Warn/Error/AI) + text search |
| **Ollama Integration** | Test, pull models, "Use in AI" syncs to AI Model tab |
| **Graceful Shutdown** | ⏻ button — confirms then stops the server cleanly |
| **Dry Run** | Preview all moves/copies before touching any files |

## AI Providers

| Provider | Setup |
|---|---|
| **Anthropic Claude** | Settings → AI Model → paste key from console.anthropic.com |
| **OpenAI GPT** | Settings → AI Model → select OpenAI → paste key |
| **Ollama (local/free)** | Settings → Ollama → Test → Pull a model → "Use in AI" |

## Files

```
ai-file-organizer/
├── index.html   — Full UI (served by Flask, or open directly)
├── server.py    — Python backend (Flask API + SQLite)
├── START.bat    — Windows one-click launcher
└── README.md
```

Data: `%APPDATA%\AIFileOrganizer\`  (metadata.db, config.json, organizer.log)

## Requirements

- Python 3.8+
- Internet (for cloud AI) or Ollama running locally
