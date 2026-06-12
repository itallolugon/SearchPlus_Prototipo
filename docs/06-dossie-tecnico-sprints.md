# Dossiê Técnico de Sprint — Search+

Projeto: **Search+** — busca semântica de imagens e documentos com IA local.
Abordagem: **SQL** (PostgreSQL/Supabase + pgvector).
Repositório: https://github.com/itallolugon/SearchPlus_Prototipo

---

## Visão geral do produto

Aplicação web que indexa pastas do computador, descreve cada imagem com IA
(LLaVA via Ollama), gera embeddings semânticos e permite buscar os arquivos em
linguagem natural ("cachorro na grama") ou por imagem (achar parecidas).

**Stack:** Frontend (HTML/CSS/JS puro) · Backend (Flask/Python) ·
Banco (PostgreSQL/Supabase + pgvector) · IA local (Ollama: LLaVA + Llama 3.2,
SBERT, CLIP).

---

## SPRINT 1 — Núcleo de busca semântica e indexação

**Objetivo:** ter o motor de busca funcionando — indexar arquivos, descrever com
IA e buscar por significado.

| História de usuário | Tarefas técnicas | Commits | Status |
|---|---|---|---|
| Como usuário, quero **fazer login/cadastro** para ter minha conta | Auth com sessão Flask, hash de senha, tabela `users` | `63c8ab0`, `e8c03fb` | ✅ Concluída |
| Como usuário, quero **cadastrar pastas** para a IA monitorar | CRUD de `folders`, worker de scan em background | `39068c4`, `63c8ab0` | ✅ Concluída |
| Como usuário, quero que a IA **descreva minhas imagens** | Integração Ollama/LLaVA, pipeline `_analyze_image`, anti-alucinação | `d3ad884`, `fa92125` | ✅ Concluída |
| Como usuário, quero **buscar por texto em linguagem natural** | Embeddings SBERT, busca híbrida (SBERT+BM25), sinônimos, re-rank LLM | `41a7db2`, `81356e4`, `b6916c5`, `d3ad884` | ✅ Concluída |
| Como usuário, quero **resultados precisos** (sem falso-positivo) | Calibração de thresholds, detecção de gênero, correção do bug "kevin" | `657adf7`, `2bad7b3`, `f3539c7` | ✅ Concluída |

**Resultado da Sprint 1:** motor de busca semântica funcional, com indexação
automática e re-ranking por IA.

---

## SPRINT 2 — Banco em nuvem, organização e experiência

**Objetivo:** evoluir a arquitetura (banco na nuvem), enriquecer a organização do
acervo e refinar a experiência do usuário.

| História de usuário | Tarefas técnicas | Commits | Status |
|---|---|---|---|
| Como equipe, queremos **banco em nuvem** acessível de qualquer máquina | Migração SQLite → PostgreSQL/Supabase com pgvector, pool de conexões | `aff9614` | ✅ Concluída |
| Como usuário, quero **buscar por imagem** (achar parecidas) | Endpoint `/api/search_by_image`, embeddings CLIP, drag&drop | `2091a8b` | ✅ Concluída |
| Como usuário, quero **organizar em coleções** | Tabelas `collections`/`collection_files`, CRUD, capas em mosaico | `cb463be`, `0d527c6`, `7668b12` | ✅ Concluída |
| Como usuário, quero **favoritar** e **ver galeria por categoria** | Favoritos, `/api/gallery`, classificação por campos da IA | `5769480`, `f36cef2` | ✅ Concluída |
| Como usuário, quero **filtrar buscas** (data, tamanho, pasta) | Busca avançada com filtros no SQL | `e5fcdb3` | ✅ Concluída |
| Como usuário, quero **personalizar e compartilhar o tema** | Exportar/importar tema (JSON), cores, fundo | `8f8d275` | ✅ Concluída |
| Como usuário, quero uma **interface organizada** | Menu lateral (hambúrguer), toasts, modal de ajuda, atalhos | `0d527c6`, `79e2518`, `ce8ae60` | ✅ Concluída |
| Como usuário, quero **configurações que funcionem** | Blacklist de pastas, notificações, modo privado | `22e8c2d` | ✅ Concluída |

**Resultado da Sprint 2:** banco em nuvem, busca visual, coleções, galeria,
personalização e UX refinada — com várias correções de bugs validadas.

---

## Integração Modelagem ↔ Scrum ↔ Código

- **Cada história** acima tem commits rastreáveis no Git (coluna "Commits").
- **Modelagem e código evoluíram juntos:** o DER ([`04-der.puml`](04-der.puml))
  reflete exatamente o `schema.sql` implementado; o Diagrama de Sequência
  ([`03-sequencia-crud-colecoes.puml`](03-sequencia-crud-colecoes.puml)) descreve
  o fluxo real do CRUD de coleções.
- **Evolução de arquitetura documentada:** a migração SQLite → Supabase
  (commit `aff9614`) é um marco arquitetural registrado.

---

## Critérios de "pronto" (Definition of Done)
Uma história só foi considerada concluída quando:
1. Código no `main` (via merge), funcionando ponta a ponta;
2. Backend + frontend integrados e testados manualmente/por API;
3. Sem regressão nas buscas existentes.
