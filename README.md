# ResearchGit

ResearchGit is a collaborative, version-controlled workspace for research teams. It applies familiar Git concepts to research materials: documents, PDFs, and chat exports are stored as artifacts; each edit creates an artifact version; and commits create immutable, branch-specific snapshots of the research corpus.

The application lets a team explore competing research directions without losing context. A branch-aware retrieval system ensures that search and research chat use only the artifact versions visible from the selected branch. Teams can compare branches, review proposed changes, merge work, resolve text conflicts, collaborate in document editors, and discuss or annotate sources in context.

## What it includes

- Workspace accounts, roles, invitations, and session-based authentication.
- Upload and processing support for Markdown, text files, PDFs, and chat-export JSON files.
- Editable research documents with real-time collaboration presence.
- Artifact version history, working changes, commits, branches, comparisons, and merge-conflict resolution.
- Branch-aware hybrid search and citation-backed research chat.
- In-context document comments, PDF annotations, workspace/branch/artifact discussions, mentions, notifications, activity, and research reviews.
- A FastAPI backend, Next.js frontend, and PostgreSQL database with the `pgvector` extension.

## Architecture

| Component | Location | Purpose |
| --- | --- | --- |
| Frontend | `web/` | Next.js 15 and React interface, served on port 3000. |
| Backend | `backend/` | FastAPI API, WebSocket collaboration endpoint, ingestion, versioning, and retrieval services, served on port 8000. |
| Database | Docker service `db` | PostgreSQL 16 with `pgvector` for application data and embeddings. |
| File storage | `backend/storage/` in Docker | Stores uploaded artifact files and generated versions. |

## Prerequisites

For the containerized setup, install:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Docker Compose v2.

For local development, install:

- Python 3.12+
- Node.js 22+ and npm
- PostgreSQL 16+ with the `pgvector` extension

Docker Desktop is still useful, but optional, if you prefer to run only the PostgreSQL/pgvector database in a container.

The default configuration uses Ollama for answer generation. To use it, install [Ollama](https://ollama.com/) and pull the configured model:

```bash
ollama pull qwen2.5:3b
```

Ollama is optional: set `LLM_PROVIDER=extractive` to use source extracts without a local model service, or configure the optional OpenAI-compatible provider as described in [Configuration](#configuration).

## How to run

Choose one of these options:

- **With Docker:** run the database, backend, and frontend as containers.
- **Without Docker:** run PostgreSQL, the backend, and the frontend directly on your machine.

### With Docker

From the repository root:

```bash
cp .env.example .env
docker compose up --build
```

Once the services are running, open:

- Frontend: <http://localhost:3000>
- Backend API: <http://localhost:8000>
- Interactive API documentation: <http://localhost:8000/docs>

The backend automatically applies database migrations when its container starts. Stop the stack with `Ctrl+C`; run it in the background with `docker compose up --build -d`, and stop it later with:

```bash
docker compose down
```

### Without Docker

Use this workflow when you want every service to run directly on your machine. It requires PostgreSQL 16+ with the `pgvector` extension installed, as well as Python 3.12+, Node.js 22+, and npm.

#### 1. Create the local database

Create a PostgreSQL user and database (enter a password for `researchgit` when prompted):

```bash
createuser -P researchgit
createdb -O researchgit researchgit
psql -U researchgit -d researchgit -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If you use an existing PostgreSQL user instead, substitute its credentials in the `DATABASE_URL` below. `pgvector` must be installed on the PostgreSQL server before the extension can be created.

#### 2. Configure and run the backend

Create a backend-local environment file:

```bash
cp .env.example backend/.env
```

In `backend/.env`, change this line:

```dotenv
DATABASE_URL=postgresql+asyncpg://researchgit:researchgit@localhost:5432/researchgit
```

Then install dependencies, apply migrations, and start the FastAPI development server:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn researchgit.main:app --reload --host 0.0.0.0 --port 8000
```

Leave this terminal running. On Windows, activate the virtual environment with `.venv\\Scripts\\activate` instead.

#### 3. Configure and run the frontend

Open a second terminal from the repository root:

```bash
cd web
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. The frontend development server reloads automatically as you edit files.

To stop locally managed services, use the service manager for your operating system or stop the terminal processes with `Ctrl+C`.

#### Optional: use Docker only for the database

If you do not have PostgreSQL with pgvector installed locally, you can run only the database in Docker and still use the local backend and frontend steps above. Start it with:

```bash
cp .env.example .env
docker compose up db -d
```

Use the same local `DATABASE_URL` containing `@localhost:5432`, then stop the database later with `docker compose stop db`.

## Configuration

Copy `.env.example` before changing configuration. Docker Compose reads `.env` from the repository root; the locally run backend reads `backend/.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | Docker: host `db` | Async SQLAlchemy database connection URL. Use `localhost` when running the backend outside Docker. |
| `STORAGE_ROOT` | `./storage` | Directory for uploaded files and artifact versions. |
| `MAX_UPLOAD_BYTES` | `26214400` | Maximum upload size in bytes (25 MiB). |
| `EMBEDDING_PROVIDER` | `deterministic` | Embedding strategy used during ingestion. |
| `LLM_PROVIDER` | `ollama` | Set to `ollama`, `extractive`, or `openai`. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `qwen2.5:3b` | Local Ollama endpoint and model. |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | empty / OpenAI API URL | Used when `LLM_PROVIDER=openai`. |
| `CHAT_MODEL` / `EMBEDDING_MODEL` | `gpt-4o-mini` / `text-embedding-3-small` | Models used by the OpenAI-compatible provider. |
| `CORS_ORIGINS` | local frontend URLs | Comma-separated allowed browser origins. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` when serving the application over HTTPS. |

## Demo data

With the Docker stack running, seed a small workspace and initial research corpus:

```bash
docker compose exec backend researchgit-seed
```

The seed account is `anoushka@example.test` with password `researchgit-demo`. It creates an **Autonomous systems evidence** workspace, a protected `main` branch, a `counter-hypothesis` branch, two starter documents, and an initial commit.

## Tests

After installing the backend development dependencies, run the test suite from the repository root:

```bash
cd backend
source .venv/bin/activate
cd ..
pytest
```

## Common commands

```bash
# Rebuild and start every service
docker compose up --build

# View container logs
docker compose logs -f backend
docker compose logs -f web

# Stop containers while retaining database data
docker compose down

# Run the production frontend build locally
cd web && npm run build && npm start
```
