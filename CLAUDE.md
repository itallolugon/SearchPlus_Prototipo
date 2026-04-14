# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## How to Run

**Start the backend (serves both API and frontend):**
```bash
py backend/app.py
```
Access the app at `http://127.0.0.1:5000`. There is no separate frontend dev server — Flask serves `index.html`, `style.css`, and `script.js` directly from the project root.

**Install Python dependencies:**
```bash
py -m pip install -r backend/requirements.txt
```

**Required external services:**
- Ollama must be running locally (`ollama serve`) with `llava` (for image analysis) and at least one text model (e.g. `llama3.2`) for query expansion.

## Architecture

This is a single-user-facing web app with a Python backend and a vanilla JS frontend. No build step, no bundler, no framework.

```
SearchPlus-front-end/
├── index.html          # Full SPA — all views in one file (modals, panels, etc.)
├── style.css           # All styles
├── script.js           # All frontend logic (~1000 lines, no framework)
├── fonts/              # Local fonts (BebasNeue, CoralPixels, MomoTrust)
└── backend/
    ├── app.py          # Flask server — API + static file serving (~1050 lines)
    ├── requirements.txt
    └── searchplus.db   # SQLite (auto-created, not committed)
```

### Backend (backend/app.py)

Flask app that does four things:
1. **Auth** — session-based login/register with SHA-256 password hashing. User config (profile, theme, search history) stored as a JSON blob in `users.config_json`.
2. **File indexing** — a background worker thread reads from a `queue.Queue`. `_scan_folder()` walks directories and enqueues new files. `_process_worker()` dequeues and calls `_analyze_file()`.
3. **AI analysis** — `_analyze_image()` sends images to LLaVA via Ollama. PDFs use PyMuPDF, DOCX uses python-docx, TXT/CSV read directly.
4. **Semantic search** — `api_search()` expands the user's query using a text LLM (`_expandir_query()`), then runs TF-IDF cosine similarity (scikit-learn) against all processed file descriptions. Results are score-normalized so the best match = 1.0.

**Key startup sequence in `__main__`:**
```python
init_db()               # Creates SQLite tables
_detectar_modelo_texto() # Finds a text model in Ollama for query expansion
threading.Thread(target=_process_worker, daemon=True).start()
app.run(...)
```

**Database schema:** Three tables — `users`, `folders`, `files`. Files have `processado=0/1` and `descricao_ia` (the AI-generated text used for search).

**Optional deps pattern:** All heavy libs (ollama, fitz, sklearn, docx) are wrapped in `try/import` blocks with boolean flags (`OLLAMA_OK`, `SKLEARN_OK`, etc.) so the server starts even if a lib is missing.

### Frontend (script.js)

No framework. All state lives in:
- `window.resultadosAtuais` — current search results array
- `currentConfig` — user config object mirrored from the server
- `_historicoCache` — search history array (local cache of server state)
- `filtroAtual` — active filter string (`'all'`, `'imagem'`, `'documento'`, `'midia'`)

**Flow:**
1. On load: `carregarConfiguracoesUX()` fetches and applies theme/profile, then `check_session` determines if the user goes to login or main app.
2. Search: `realizarBusca()` → POST `/api/search` with `query` + `filtroAtual` → `renderizarResultados()` splits results into "Melhores" (score ≥ 0.60) and "Semânticos" grids.
3. File details: `abrirPainelLateral(index)` opens the right-side panel using `window.resultadosAtuais[index]`.

**Native Windows dialogs:** The JS calls `/api/choose_folder` and `/api/choose_image` which open tkinter file pickers on the server side. This only works when the server is running on the same Windows machine.

### API endpoints summary

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/login` | Authenticate |
| POST | `/api/register` | Create account |
| GET/POST | `/api/config` | User config (profile, theme, history) |
| GET/POST/DELETE | `/api/folders` | Manage monitored folders |
| POST | `/api/analyze_folders` | Trigger re-scan of all folders |
| POST | `/api/reanalyze` | Re-queue files with bad/fallback descriptions |
| GET/POST | `/api/search` | Semantic search |
| GET/POST/DELETE | `/api/search_history` | Search history |
| GET | `/api/file/<path>` | Serve a local file by absolute path |
| GET | `/api/choose_folder` | Open Windows folder picker dialog |
| GET | `/api/choose_image` | Open Windows image picker dialog |
| GET | `/api/open_location` | Open Explorer with file selected |
| GET | `/api/status` | AI worker queue status |
| GET | `/api/debug/files` | Show all indexed files with description previews |

## Important Notes

- **Python launcher:** Use `py` instead of `python` on this Windows machine (Python 3.14).
- **Same-origin setup:** Flask serves the frontend, so there are no CORS issues in normal use. The CORS config exists only for development with a separate static server (e.g. Live Server on port 5500).
- **No frontend credentials header needed:** Since frontend and API share the same origin (`127.0.0.1:5000`), fetch calls automatically include cookies.
- **`searchplus.db` is gitignored** — deleting it resets all users and indexed files. After deletion, old session cookies reference non-existent users; `check_session` detects this and clears stale sessions.
- **Query expansion latency:** `_expandir_query()` calls a local LLM synchronously during each search request. If the text model is slow, search will be slow. The function falls back gracefully to the original query if Ollama fails.
