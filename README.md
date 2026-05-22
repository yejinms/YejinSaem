# YejinSaem

Kakao channel based writing feedback automation for teachers. Parents send worksheet photos through Kakao, the admin reviews AI-generated feedback, and the final message is sent through Solapi Friend Talk.

## Requirements

- Python 3.11+
- Anthropic API key for Claude vision feedback
- Solapi Kakao Friend Talk credentials

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `backend/.env`:

```env
ANTHROPIC_API_KEY=...
SOLAPI_API_KEY=...
SOLAPI_API_SECRET=...
SOLAPI_SENDER_KEY=...
SOLAPI_SENDER_PHONE=01012345678
ADMIN_PASSWORD=change-this
```

`ADMIN_PASSWORD` protects `/admin/*` endpoints when set. The browser dashboard asks for this password and stores it in `sessionStorage` for the current tab.

## Run

```bash
cd backend
source .venv/bin/activate
python main.py
```

Open:

- Admin dashboard: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Core Workflow

1. Register a parent in the admin dashboard with Kakao user ID and phone number.
2. Parent sends a worksheet photo through Kakao.
3. Admin opens the pending submission.
4. Admin selects level and stage, then generates feedback.
5. Admin edits the draft and sends it.
6. If Solapi sending fails, the submission remains `approved` and can be retried.

Admins can also create a submission without Kakao. In the pending tab, select a parent, choose an image file or paste an image from the clipboard, then create the submission. The generated submission opens the same feedback workflow.

## Deploy on Railway

Deploy from the **repository root** (see `railway.toml`). Do not set Root Directory to `backend` only.

1. Connect the GitHub repo on [Railway](https://railway.com/).
2. Add a Volume mounted at `/data` and set `DATABASE_URL=sqlite:////data/yejinsaem.db`, `UPLOAD_DIR=/data/uploads`.
3. Copy variables from `backend/.env` into Railway **Variables** (never commit secrets).
4. **Generate Domain** under Networking.

Step-by-step (Korean): [docs/railway-deploy.md](docs/railway-deploy.md)

## Kakao Webhook (Open Builder)

After Railway gives you a public HTTPS domain, set the skill Endpoint URL to:

```text
https://<your-railway-domain>/kakao/webhook
```

Unregistered Kakao users do not create submissions. They receive a registration-needed response.

## Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest tests
```

The tests use a temporary SQLite database and mock external Claude/Solapi calls where needed.

## Useful Checks

```bash
python -m compileall backend
python -m pytest backend/tests
```

Run the second command from the repository root, or use `python -m pytest tests` from `backend/`.
