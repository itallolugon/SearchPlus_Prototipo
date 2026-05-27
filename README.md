# Search+

Aplicativo de busca semântica para imagens (e documentos): você aponta para uma pasta e pesquisa em linguagem natural — tipo "cachorro brincando" ou "prato de comida com kebab".

**Como funciona:**
- A IA de análise (LLaVA + embeddings) roda 100% local no seu computador via Ollama.
- O banco de dados fica no **Supabase** (Postgres com pgvector) — gratuito, free tier permanente.
- Cada usuário precisa de um arquivo `.env` com suas credenciais Supabase.

---

## 🛠️ Setup e uso

### Pré-requisitos

- **Python 3.10+** (no Windows, usar `py`; o projeto foi desenvolvido com Python 3.14)
- **Ollama** — https://ollama.com/download
  ```bash
  ollama serve
  ollama pull llava:13b   # análise de imagens
  ollama pull llama3.2    # re-rank e expansão de queries
  ```
- Navegador moderno (Chrome, Edge, Firefox)

### Setup

```bash
git clone https://github.com/itallolugon/SearchPlus_Prototipo
cd SearchPlus_Prototipo
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r backend/requirements.txt
```

### Configurar o Supabase (banco de dados)

1. Crie uma conta gratuita em [supabase.com](https://supabase.com) e crie um projeto novo.
2. Em **Database → Extensions**, habilite a extensão `vector`.
3. Em **Project Settings → API**, copie a Project URL, anon key e service_role key.
4. Em **Project Settings → Database**, copie a connection string (URI).
5. Copie `backend/.env.example` para `backend/.env` e cole suas credenciais.
6. Rode uma vez para criar as tabelas (o app faz isso automaticamente na primeira execução, lendo `backend/schema.sql`).

### Rodar

Com o Ollama rodando em paralelo:

```bash
py backend/app.py
```

Acesse `http://127.0.0.1:5000`. O Flask serve tanto a API quanto o frontend (`index.html`, `style.css`, `script.js`) — não há build step nem servidor frontend separado.

### Dependências

| Biblioteca | Uso |
|------------|-----|
| `flask` + `flask-cors` | Servidor web, API e CORS |
| `psycopg2-binary` | Driver Postgres (Supabase) |
| `pgvector` | Adapter pgvector pra embeddings nativos |
| `python-dotenv` | Carrega credenciais do `.env` |
| `ollama` | Cliente Python para LLaVA + Llama 3.2 |
| `sentence-transformers` | Embeddings semânticos (SBERT multilingual, 384 dim) |
| `scikit-learn` + `numpy` | Cosine similarity auxiliar (CLIP visual) |
| `rank_bm25` | Ranking BM25 (camada keyword da busca híbrida) |
| `PyMuPDF` (fitz) | Extração de texto de PDFs |
| `python-docx` | Extração de texto de DOCX |
| `Pillow` | Manipulação e resize de imagens |

### Estrutura

```
SearchPlus_Prototipo/
├── index.html               # SPA completa (modais, painéis, views)
├── style.css                # Estilos
├── script.js                # Lógica do frontend (vanilla JS)
├── fonts/                   # BebasNeue, CoralPixels, MomoTrust
├── backend/
│   ├── app.py               # Flask: API + arquivos estáticos + worker de IA
│   ├── requirements.txt
│   ├── schema.sql           # Schema Postgres com pgvector
│   ├── .env.example         # Template de credenciais Supabase
│   └── .env                 # Credenciais reais (gitignored)
└── fonts/                   # Fontes locais
```

### Como funciona a busca

Pipeline híbrido com 3 camadas + re-ranking, usando **pgvector** no Supabase:

1. **SBERT no banco** (`embedding <=> query_vec` com índice HNSW) — top 100 candidatos por similaridade vetorial, ordenados pelo Postgres. **Sem carregar embeddings em RAM**.
2. **BM25** — ranking por palavra-chave sobre os 100 candidatos
3. **CLIP** (opcional) — match visual texto↔pixel direto, quando disponível
4. **LLM-juiz** (`llama3.2`) — re-rank dos top-20 com salvaguardas anti-rejeição

Detalhes adicionais:

- Sinônimos expandidos nos **dois lados** (query e documento) — "cão" na descrição casa com busca por "cachorro"
- Variantes morfológicas singular↔plural pra cobrir o plural nasal pt-BR (`homem`↔`homens`)
- Threshold adaptativo: 0.35 → 0.30 quando a busca retorna vazio
- Anti-alucinação no LLaVA: `temperature=0`, `top_p=0.5`, prompt explícito
- Worker resiliente: descrição em fallback (`"Imagem: x.jpg"`) **não** marca arquivo como processado, então uma próxima varredura tenta de novo

### Notas

- **Windows-only para diálogos nativos**: `/api/choose_folder` e `/api/choose_image` usam `tkinter`. Em Linux/macOS essas rotas falham — o resto do app funciona.
- **Banco de dados**: Postgres no Supabase, configurado via `backend/.env`. O schema é criado automaticamente pelo `app.py` (lê `backend/schema.sql`). Apagar as tabelas no dashboard do Supabase reseta usuários e arquivos.
- **Latência da busca**: o re-rank com LLM adiciona ~300 ms quando há 2+ candidatos. Em caso de falha do Ollama, degrada gracioso para SBERT+BM25 puro.
