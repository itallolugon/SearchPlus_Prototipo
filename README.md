# Search+

Aplicativo de busca semântica local: você aponta para uma pasta de imagens (e documentos) e pesquisa por elas escrevendo o que quer encontrar em linguagem natural — tipo "cachorro brincando" ou "prato de comida com kebab". A IA roda 100% no seu computador, sem mandar nada pra nuvem.

---

## 🟢 Quero só USAR o app (não sei programar)

### O que você precisa
- Windows 10 ou 11
- ~12 GB livres em disco
- Internet (só na primeira instalação)
- ~30-50 minutos para instalar tudo

### Passo 1: Conseguir o pacote `SearchPlus_Portatil.zip`

**Opção A** — alguém já te mandou o ZIP. Pula pra "Passo 2".

**Opção B** — você quer baixar do GitHub. Faça assim:

1. Vá em: https://github.com/itallolugon/SearchPlus_Prototipo
2. Clique no botão verde **`<> Code`** → **`Download ZIP`**
3. Descompacte o ZIP que baixou
4. Entre na pasta descompactada e vá em **`installer/`**
5. Clique 2 vezes em **`empacotar.bat`** — ele cria a pasta `dist/` com o arquivo `SearchPlus_Portatil.zip` pronto

### Passo 2: Instalar e usar

1. **Descompacte** o `SearchPlus_Portatil.zip` em qualquer pasta (ex: `C:\Search+`).
2. **Abra** o arquivo `INSTRUTIVO.txt` dentro da pasta — ele explica tudo passo a passo.
3. Em resumo, você vai clicar 2 vezes em 3 arquivos, **na ordem**:
   - `1-INSTALAR-DEPENDENCIAS.bat` — instala o Python e as bibliotecas (~10 min)
   - `2-INSTALAR-OLLAMA.bat` — instala o Ollama e baixa os modelos de IA (~30 min, ~10 GB)
   - `INICIAR.bat` — sobe o app e abre o navegador

A partir do dia seguinte, é só clicar em **`INICIAR.bat`** sempre que quiser usar.

### Deu problema?

| Erro | Solução |
|---|---|
| "Python não foi encontrado" | Reinstale o Python e **marque** "Add Python to PATH" |
| "Ollama não foi encontrado" | Instale o Ollama em https://ollama.com/download/windows |
| O navegador não abre | Abra manualmente em `http://127.0.0.1:5000` |
| A busca não retorna nada | Espere a IA terminar de analisar a pasta (acompanhe pelo status no canto da tela) |

---

## 📦 Quero DISTRIBUIR o ZIP para outras pessoas

1. Clone ou baixe o repositório.
2. Rode `installer/empacotar.bat`.
3. O arquivo `dist/SearchPlus_Portatil.zip` (~270 KB) fica pronto pra enviar por WeTransfer, Drive, etc.

A pessoa que receber só precisa seguir as instruções da seção verde acima.

---

## 🛠️ Quero DESENVOLVER no projeto

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
| `ollama` | Cliente Python para LLaVA + Llama 3.2 |
| `sentence-transformers` | Embeddings semânticos (SBERT multilingual) |
| `scikit-learn` + `numpy` | Cosine similarity, fallback TF-IDF |
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
│   └── searchplus.db        # SQLite gerado em runtime (não versionado)
├── installer/               # Empacotador para distribuição
│   ├── empacotar.bat / .ps1
│   ├── 1-INSTALAR-DEPENDENCIAS.bat
│   ├── 2-INSTALAR-OLLAMA.bat
│   ├── INICIAR.bat
│   └── INSTRUTIVO.txt
└── dist/                    # ZIP gerado pelo empacotador (gitignored)
```

### Como funciona a busca

Pipeline híbrido com 3 camadas + re-ranking:

1. **SBERT** (sentence-transformers/MiniLM-L12 multilingual) — embedding semântico do texto da descrição
2. **BM25** — ranking por palavra-chave sobre descrição + nome do arquivo
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
- **Banco de dados**: `backend/searchplus.db` é gerado em runtime e está gitignored. Apagá-lo reseta usuários e arquivos indexados.
- **Latência da busca**: o re-rank com LLM adiciona ~300 ms quando há 2+ candidatos. Em caso de falha do Ollama, degrada gracioso para SBERT+BM25 puro.
