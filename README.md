# SearchPlus

Aplicação web para busca semântica local em arquivos (imagens, PDFs, DOCX, TXT, CSV) com análise por IA. O backend em Flask serve uma API e os arquivos estáticos do frontend (HTML/CSS/JS vanilla, sem framework).

## Pré-requisitos

### 1. Python 3.10+
- No Windows, usar o launcher `py` (o projeto foi desenvolvido com Python 3.14).
- Download: https://www.python.org/downloads/

### 2. Ollama (runtime local de modelos de IA)
- Download: https://ollama.com/download
- Após instalar, iniciar o serviço:
  ```bash
  ollama serve
  ```
- Baixar os modelos obrigatórios:
  ```bash
  ollama pull llava
  ollama pull llama3.2
  ```
  - `llava` → análise/descrição de imagens
  - `llama3.2` (ou outro modelo de texto compatível) → expansão de queries com sinônimos

> O sistema detecta automaticamente o modelo de texto disponível seguindo a ordem de preferência: `llama3 > llama2 > mistral > gemma > phi > qwen > deepseek > orca`.

### 3. Navegador moderno
Chrome, Edge ou Firefox atualizados.

## Instalação

1. Clonar o repositório:
   ```bash
   git clone <URL_DO_REPOSITORIO>
   cd SearchPlus-front-end
   ```

2. (Recomendado) Criar um ambiente virtual Python:
   ```bash
   py -m venv .venv
   .venv\Scripts\activate        # Windows
   source .venv/bin/activate     # Linux/macOS
   ```

3. Instalar as dependências Python:
   ```bash
   py -m pip install -r backend/requirements.txt
   ```

### Dependências Python (backend/requirements.txt)

| Biblioteca | Uso |
|------------|-----|
| `flask` | Servidor web e API |
| `flask-cors` | CORS (apenas para dev com static server separado) |
| `ollama` | Cliente Python para o Ollama (LLaVA + LLM de texto) |
| `scikit-learn` | TF-IDF e cosine similarity para busca semântica |
| `numpy` | Operações numéricas de apoio |
| `PyMuPDF` (fitz) | Extração de texto de PDFs |
| `python-docx` | Extração de texto de arquivos DOCX |
| `sentence-transformers` | Embeddings semânticos |
| `rank_bm25` | Ranking BM25 como reforço do TF-IDF |
| `Pillow` | Manipulação de imagens |

## Como executar

Com o Ollama rodando em paralelo (`ollama serve`):

```bash
py backend/app.py
```

Acessar o app em: **http://127.0.0.1:5000**

O Flask serve tanto a API quanto o frontend (`index.html`, `style.css`, `script.js`) a partir da raiz do projeto — não há build step nem servidor de frontend separado.

## Estrutura do projeto

```
SearchPlus-front-end/
├── index.html          # SPA completa (modais, painéis, views)
├── style.css           # Estilos
├── script.js           # Lógica do frontend (vanilla JS)
├── fonts/              # Fontes locais (BebasNeue, CoralPixels, MomoTrust)
└── backend/
    ├── app.py          # Flask: API + arquivos estáticos
    ├── requirements.txt
    └── searchplus.db   # SQLite (gerado automaticamente, não versionado)
```

## Observações

- **Windows apenas para diálogos nativos:** os endpoints `/api/choose_folder` e `/api/choose_image` abrem caixas de diálogo do Windows via `tkinter`. Em outros sistemas operacionais, essas rotas não funcionarão.
- **Banco de dados:** o arquivo `backend/searchplus.db` é criado automaticamente na primeira execução e está no `.gitignore`. Removê-lo reseta todos os usuários e arquivos indexados.
- **Latência da busca:** a expansão de query chama o LLM local de forma síncrona. Se o modelo de texto estiver lento, a busca será lenta. Em caso de falha do Ollama, o sistema usa a query original como fallback.
