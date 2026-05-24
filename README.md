# CodeHealer

CodeHealer is an autonomous code repair agent for Python repositories. It reads a GitHub Issue, retrieves the most relevant source file, asks an LLM to generate a patch, verifies the result inside an isolated Docker sandbox, and opens a Pull Request when the fix passes validation.

The project is designed as a practical AI infrastructure prototype for issue-driven maintenance workflows. It combines graph orchestration, code retrieval, sandbox execution, and GitHub automation into one end-to-end repair loop.

## Features

- LangGraph orchestration
  - Models the repair workflow as an explicit state machine.
  - Starts with verification, retries code generation when tests fail, and stops after success or retry exhaustion.

- Code-level RAG with ChromaDB
  - Walks the target repository's Python source files.
  - Splits code into semantic chunks.
  - Embeds chunks into an in-memory Chroma vector store.
  - Retrieves the most relevant file for the current GitHub Issue.

- Docker sandbox verification
  - Runs candidate code and pytest tests in a disposable `python:3.10-slim` container.
  - Captures stdout, stderr, exit code, and timeout failures.
  - Cleans up containers after each verification attempt.

- GitHub Issue to Pull Request automation
  - Reads Issue title and body from a target repository.
  - Creates an isolated repair branch.
  - Updates the retrieved source file.
  - Opens a Pull Request with the sandbox verification result.

## Repository Layout

```text
.
├── core_engine.py          # LangGraph repair engine, LLM coder, Docker sandbox executor
├── run_github_agent.py     # GitHub connector, code retriever, and production entry point
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

## Requirements

- Python 3.10 or later
- Docker Desktop or a reachable Docker daemon
- A GitHub Personal Access Token
- An OpenAI-compatible chat model endpoint
- An OpenAI-compatible embedding endpoint

The current embedding adapter is configured for Alibaba Cloud DashScope OpenAI-compatible embeddings with:

```text
text-embedding-v1
```

## Installation

```bash
pip install -r requirements.txt
```

## Environment Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GITHUB_TOKEN=your_github_personal_access_token
TARGET_REPO=your_github_username/test-repo
TARGET_ISSUE_NUMBER=1
```

Configuration reference:

- `OPENAI_API_KEY`: API key for the chat and embedding provider.
- `OPENAI_API_BASE`: OpenAI-compatible API base URL.
- `LLM_MODEL_NAME`: Chat model used to generate code fixes.
- `GITHUB_TOKEN`: GitHub token with repository read/write and Pull Request permissions.
- `TARGET_REPO`: Target repository in `owner/repo` format.
- `TARGET_ISSUE_NUMBER`: GitHub Issue number to process.

## Usage

Start Docker, then run:

```bash
python run_github_agent.py
```

The agent will:

1. Load configuration from `.env`.
2. Read the configured GitHub Issue.
3. Index Python source files from the repository default branch.
4. Retrieve the most relevant source file with ChromaDB.
5. Build an `AgentState` for the repair engine.
6. Run the LangGraph repair and verification loop.
7. Execute pytest inside Docker.
8. Create a Pull Request if verification succeeds.

The execution report prints the retrieved file, resolution status, iteration count, sandbox output, and Pull Request URL when available.

## Current Validation Harness

`run_github_agent.py` currently ships with a small demonstration pytest harness:

```python
from solution import safe_divide


def test_normal_division() -> None:
    assert safe_divide(10, 2) == 5


def test_division_by_zero_returns_zero() -> None:
    assert safe_divide(10, 0) == 0.0
```

This is intentionally simple so the full repair loop can be tested against a controlled repository. For real projects, replace `DEMO_TEST_CODE` with tests discovered from the repository, tests generated from the Issue, or a project-specific validation command.

## Architecture

```text
GitHub Issue
    |
    v
GitHubConnector
    |
    v
CodebaseRetriever
    |
    v
ChromaDB top-1 source file retrieval
    |
    v
CodeHealerEngine
    |
    +--> DockerSandboxExecutor
    |
    +--> LangChainCoder
    |
    v
Verified patch
    |
    v
GitHub Pull Request
```

## Notes

- The retriever currently ignores `test`, `tests`, `__pycache__`, `.venv`, and `venv` directories.
- The retriever skips Python files named `test_*.py` or `*_test.py`.
- The Docker sandbox writes candidate code to `solution.py` and test code to `test_code.py`.
- The repair loop retries until the test passes or the maximum retry count is reached.

## Troubleshooting

### Docker is not available

Make sure Docker Desktop is running and verify access from the terminal:

```bash
docker ps
```

### Embedding model errors

The custom embedding adapter uses Alibaba Cloud's compatible model:

```text
text-embedding-v1
```

If you use another provider, update `CustomAliyunEmbeddings` in `run_github_agent.py`.

### Pull Request creation fails

Check that:

- `GITHUB_TOKEN` has access to the target repository.
- The token can create branches, update contents, and open Pull Requests.
- The target repository has a valid default branch.
- Branch protection rules do not block automated updates.

### Retrieval selects the wrong file

The current implementation uses top-1 vector retrieval. For larger repositories, consider adding:

- Top-k file voting
- Hybrid lexical and vector search
- AST or symbol indexing
- Test file retrieval
- LLM reranking over candidate files

## Security

CodeHealer can create branches, commit code, and open Pull Requests. Run it only against repositories you own or are explicitly authorized to modify. Store API keys and GitHub tokens in `.env`, and never commit secrets to source control.

