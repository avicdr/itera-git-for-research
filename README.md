# ResearchGit

ResearchGit is a versioned research workspace: artifacts are processed into a branch-aware corpus, commits form immutable snapshots, and research chat retrieves only the versions visible from its branch.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:3000. API documentation: http://localhost:8000/docs.

For local backend development: `cd backend && pip install -e '.[dev]' && uvicorn researchgit.main:app --reload`.

## Demo

`docker compose exec backend researchgit-seed` creates three users, a workspace, documents, branches and a merge conflict.

Set `EMBEDDING_PROVIDER=deterministic` and run a local Ollama model for private source-grounded answers. Install Ollama, run `ollama pull qwen2.5:3b`, and use `LLM_PROVIDER=ollama` with `OLLAMA_BASE_URL=http://127.0.0.1:11434`. Set `LLM_PROVIDER=extractive` if no local model service is available. An OpenAI-compatible provider remains optional.
