# Skill Share Backend (FastAPI + psycopg2)

## Run locally
1. python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
2. pip install -r requirements.txt
3. cp .env.example .env  # fill DATABASE_URL
4. uvicorn app.main:app --reload --port 8000