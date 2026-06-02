# Search+

Aplicativo de **busca semântica para imagens e documentos**. Em vez de procurar arquivos pelo nome, você descreve o que quer encontrar em linguagem natural — tipo *"cachorro brincando na grama"*, *"prato de comida com kebab"* ou *"foto de festa à noite"* — e a IA encontra os arquivos pelo significado.

---

## O que ele faz

- **Indexa pastas do computador**: analisa cada imagem e documento com IA, gerando uma descrição e um vetor semântico (embedding).
- **Busca por significado**: entende sinônimos e linguagem natural. Buscar "cachorro" encontra uma imagem que a IA descreveu como "cão" ou "filhote".
- **Busca híbrida**: combina similaridade semântica, palavras-chave e (opcionalmente) análise visual direta da imagem.
- **Favoritos, histórico e perfis**: organiza e acelera buscas recorrentes.

## Como funciona (visão geral)

| Camada | Tecnologia | Papel |
|--------|-----------|-------|
| Análise de imagem | LLaVA (via Ollama, local) | Descreve o conteúdo de cada imagem |
| Embeddings | SBERT multilingual | Transforma texto em vetores para busca semântica |
| Banco de dados | Postgres + pgvector (Supabase) | Guarda arquivos, usuários e vetores na nuvem |
| Re-ranking | Llama 3.2 (via Ollama, local) | Reordena os resultados por relevância |
| Frontend | HTML/CSS/JS puro | Interface, sem framework nem build step |
| Backend | Flask (Python) | API + serve o frontend + worker de IA |

A IA de análise roda **100% local** na máquina do usuário (via Ollama). O banco de dados fica na **nuvem** (Supabase), o que permite acessar os mesmos dados de qualquer máquina.

## Pipeline de busca

A busca passa por 4 camadas combinadas:

1. **SBERT no banco** — o Postgres encontra os candidatos mais próximos por similaridade vetorial (índice HNSW), sem carregar nada em memória.
2. **BM25** — reforço por palavra-chave sobre os candidatos.
3. **CLIP** (opcional) — match visual direto entre o texto buscado e os pixels da imagem.
4. **LLM-juiz** — o Llama 3.2 reordena os melhores resultados por relevância real.

Detalhes que aumentam a precisão: expansão de sinônimos nos dois lados (query e descrição), variantes singular↔plural do português, threshold adaptativo e anti-alucinação no modelo de visão.

## Status do projeto

Protótipo funcional. A análise de imagem hoje roda localmente via Ollama; há um plano em estudo de migrar para uma IA via API (mais rápida e de maior qualidade). Consulte o `RELATORIO.txt` para o estado técnico detalhado, decisões de arquitetura e pendências.
