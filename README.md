# Search+

Aplicativo de **busca semântica para imagens e documentos**. Em vez de procurar arquivos pelo nome, você descreve o que quer encontrar em linguagem natural — tipo *"cachorro brincando na grama"*, *"prato de comida com kebab"* ou *"foto de festa à noite"* — e a IA encontra os arquivos pelo significado.

---

## O que ele faz

- **Indexa pastas do computador**: gera um vetor visual de cada imagem e extrai o texto dos documentos.
- **Busca por significado**: entende sinônimos e linguagem natural. Buscar "cachorro" encontra a foto de um filhote, mesmo que o arquivo se chame `IMG_8472.jpg`.
- **Busca híbrida**: combina similaridade semântica, palavras-chave e análise visual direta da imagem.
- **A IA só trabalha quando você busca**: as imagens são indexadas na hora do upload de forma instantânea; o Claude só descreve e julga as candidatas quando você faz uma pesquisa.
- **Favoritos, coleções, galeria por categoria e histórico**.

## Como funciona

| Camada | Tecnologia | Onde roda |
|--------|-----------|-----------|
| Descrição de imagens | Claude (vision) | API (nuvem) |
| Julgamento de relevância | Claude | API (nuvem) |
| Embeddings de texto | SBERT multilingual (384 dim) | Local |
| Embeddings visuais | CLIP ViT-B-32 (512 dim) | Local |
| Banco de dados | Postgres + pgvector | Supabase (nuvem) |
| Frontend | HTML/CSS/JS puro | Sem framework nem build step |
| Backend | Flask (Python) | API + serve o frontend + worker de indexação |

Os **embeddings rodam localmente** (o motor da busca vetorial). A **descrição e o julgamento** usam a API do Claude. O banco fica no Supabase, então os mesmos dados são acessíveis de qualquer máquina.

## Pipeline de busca (indexação lazy)

**No upload** — rápido e sem custo: cada imagem recebe apenas seu vetor visual (CLIP, local). Nenhuma chamada à IA é feita.

**Na busca** — o Claude entra em ação:

1. **CLIP** compara sua frase com os pixels das imagens e levanta as candidatas visualmente parecidas.
2. **SBERT** (pgvector + índice HNSW) traz os candidatos por similaridade de texto.
3. **BM25** reforça o match por palavra-chave.
4. **Claude descreve sob demanda** as até 5 imagens mais promissoras que ainda não têm descrição — e salva o resultado, então buscas seguintes são instantâneas.
5. **Claude julga** quais resultados realmente correspondem à busca e descarta os parecidos-mas-errados (um gato não aparece numa busca por cachorro).

Outros detalhes que aumentam a precisão: expansão de sinônimos nos dois lados, variantes singular↔plural do português, threshold adaptativo e prompt anti-alucinação na descrição.

---

## Vai trabalhar no frontend?

Comece por aqui — não precisa de banco de dados, de modelos de IA nem de chave de API:

```bash
py -m pip install flask flask-cors
py backend/mock_server.py
```

Abra `http://127.0.0.1:5001` e o Search+ roda inteiro com dados fictícios. Qualquer usuário e senha entram.

| Documento | Conteúdo |
|---|---|
| [docs/FRONTEND.md](docs/FRONTEND.md) | Guia de substituição da interface: o que trocar, o que não tocar, fluxos a entregar |
| [docs/API.md](docs/API.md) | Contrato da API: payloads, respostas e erros de cada endpoint |
| [AGENTS.md](AGENTS.md) | Instruções para agentes de IA trabalhando neste repositório |

A interface é substituível por completo; o backend fica como está. Detalhes em [docs/FRONTEND.md](docs/FRONTEND.md).

---

# Como instalar em outro computador

Guia completo para colocar o Search+ funcionando numa máquina nova (Windows). Existe também o [COMO_RODAR.txt](COMO_RODAR.txt), escrito em linguagem mais simples para usuários leigos.

### Antes de começar, você vai precisar de:

- **Windows** (os seletores de pasta usam diálogos nativos do Windows)
- **Internet** — o app usa a IA e o banco de dados na nuvem
- Uma **chave de API do Claude** e a **string de conexão do banco** (detalhes no Passo 3)
- Cerca de **15 minutos** e **~2 GB de espaço** livre

---

## Passo 1 — Instalar o Python

1. Baixe em [python.org/downloads](https://www.python.org/downloads/) (versão 3.10 ou mais nova).
2. Ao abrir o instalador, **marque a caixa "Add Python to PATH"** na primeira tela. Sem isso, os comandos não funcionam.
3. Clique em *Install Now*.

Confira se deu certo abrindo o Prompt de Comando (tecla Windows → digite `cmd`) e rodando:

```bat
py --version
```

Deve aparecer algo como `Python 3.14.4`.

> O `tkinter` (usado nos seletores de pasta) já vem incluído no instalador oficial do python.org. Se você instalou o Python de outra fonte e o app reclamar dele, reinstale pelo site oficial.

## Passo 2 — Baixar o projeto

Clone o repositório ou copie a pasta do projeto para o computador:

```bat
git clone https://github.com/itallolugon/SearchPlus_Prototipo.git
cd SearchPlus_Prototipo
```

Se você recebeu a pasta por pendrive ou drive, **copie-a para o disco local** (Documentos ou Área de Trabalho) em vez de rodar direto do pendrive — fica bem mais rápido.

## Passo 3 — Criar o arquivo de credenciais (`backend/.env`)

Esta é a parte mais importante, e a única que não vem pronta no repositório: as credenciais **não são versionadas no Git** por segurança.

Crie um arquivo chamado `.env` **dentro da pasta `backend`** (o caminho final é `backend/.env`) com este conteúdo:

```env
# Conexão com o banco Postgres (Supabase)
DATABASE_URL=postgresql://usuario:senha@host:5432/postgres

# Chave da API do Claude (Anthropic)
ANTHROPIC_API_KEY=sk-ant-sua-chave-aqui
```

Regras que evitam dor de cabeça:

- **Sem espaços** em volta do `=` — `ANTHROPIC_API_KEY=sk-ant-...`, nunca `ANTHROPIC_API_KEY= sk-ant-...`
- **Sem aspas** em volta dos valores
- O arquivo se chama exatamente `.env` (com o ponto, sem `.txt` no fim)

### De onde vêm esses dois valores

**`ANTHROPIC_API_KEY`** — crie em [console.anthropic.com](https://console.anthropic.com):
1. Faça login, vá em **Billing** e adicione crédito (a partir de US$ 5).
2. Vá em **API Keys** → **Create Key** → copie a chave (começa com `sk-ant-`).
3. A chave é exibida só uma vez; guarde-a em lugar seguro.

**`DATABASE_URL`** — você tem duas opções:

- **Usar um banco já existente**: peça a string de conexão a quem administra o projeto. Os dados (contas e arquivos indexados) serão compartilhados entre todos que usarem a mesma string.
- **Criar seu próprio banco** (recomendado para uso independente): crie um projeto gratuito no [supabase.com](https://supabase.com), ative a extensão **`vector`** em *Database → Extensions*, e rode o conteúdo de [backend/schema.sql](backend/schema.sql) no *SQL Editor*. A string de conexão fica em *Project Settings → Database → Connection string (URI)*.

> ⚠️ **Nunca comite o `.env` nem compartilhe essas credenciais publicamente.** Quem tem a chave da API pode gastar seu crédito, e quem tem a string do banco pode ler e apagar todos os dados. O arquivo já está no `.gitignore`.

## Passo 4 — Instalar as dependências

Abra o Prompt de Comando **dentro da pasta do projeto** (abra a pasta no Explorer, clique na barra de endereço, digite `cmd` e Enter) e rode:

```bat
py -m pip install -r backend/requirements.txt
```

Leva alguns minutos e imprime bastante texto — é normal. Isso instala o Flask, o cliente do Claude, o SBERT/CLIP (via `sentence-transformers`), o driver do Postgres e os leitores de PDF/DOCX.

## Passo 5 — Ligar o app

Dê **dois cliques em `rodar.bat`** (ou rode `py backend/app.py` no terminal).

Na **primeira execução**, o app baixa os modelos de embedding (SBERT e CLIP, cerca de **1,6 GB**). Isso acontece uma única vez — nas próximas ele carrega do cache local.

Quando o terminal mostrar as linhas abaixo, está tudo funcionando:

```
[AI] Claude ativo — descrição de imagens e re-rank da busca via API.
[AI] Sentence Transformers carregado — busca semântica ativa.
[AI] CLIP multilingual carregado — busca visual ativa.
[DB] Pool Postgres pronto (...)
  Search+ Backend iniciado!
```

O navegador abre sozinho em **http://127.0.0.1:5000**. Se não abrir, digite esse endereço manualmente. **Mantenha a janela do terminal aberta** — ela é o servidor; fechá-la desliga o app.

## Passo 6 — Usar

1. Crie uma conta na tela inicial.
2. Adicione uma pasta do computador que contenha imagens.
3. Escolha o modo de análise (**Relâmpago** = descrições mais econômicas, **Profundo** = mais minuciosas) e confirme. A indexação só começa depois da sua confirmação.
4. Busque em português natural: *"cachorro na grama"*, *"nota fiscal"*, *"prato de comida"*.

A **primeira busca** por um assunto novo demora alguns segundos, porque o Claude está descrevendo as imagens candidatas naquele momento. As buscas seguintes usam o cache e respondem em cerca de 1 segundo.

Para desligar, feche a janela do terminal. Para religar, basta rodar o `rodar.bat` de novo — os passos 1, 3 e 4 são só da primeira vez.

---

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `py não é reconhecido` | O Python foi instalado sem marcar *Add Python to PATH*. Reinstale marcando a caixa. |
| A janela abre e fecha imediatamente | Dependências não instaladas. Refaça o Passo 4 e leia a mensagem de erro no terminal. |
| `ANTHROPIC_API_KEY não encontrada no .env` | O arquivo não existe, está no lugar errado (precisa ser `backend/.env`) ou a chave tem espaço/aspas. |
| Busca funciona, mas imagens não são descritas | Chave inválida ou sem crédito. Confira em *Billing* no console da Anthropic. |
| Erro de conexão com o banco | `DATABASE_URL` incorreta, ou o computador está sem internet. |
| O download dos modelos falha | Rode com `SEARCHPLUS_OFFLINE=0` (o `rodar.bat` já faz isso) e verifique a conexão. |

---

## Estrutura do projeto

```
SearchPlus_Prototipo/
├── index.html          # Interface (SPA — todas as telas num arquivo)
├── style.css           # Estilos
├── script.js           # Lógica do frontend (sem framework)
├── rodar.bat           # Atalho para ligar o servidor no Windows
├── fonts/              # Fontes locais
├── landing/            # Página de apresentação do produto (estática)
├── docs/               # Diagramas UML, DER e documentação acadêmica
└── backend/
    ├── app.py          # Servidor Flask: API, worker de indexação e busca
    ├── schema.sql      # DDL do banco (5 tabelas + índices HNSW)
    ├── requirements.txt
    └── .env            # Credenciais (você cria; não vai para o Git)
```

## Status do projeto

Protótipo funcional. A descrição de imagens e o julgamento de relevância usam a API do Claude; os embeddings rodam localmente. Consulte o [RELATORIO.md](RELATORIO.md) para o estado técnico detalhado, decisões de arquitetura e pendências.
