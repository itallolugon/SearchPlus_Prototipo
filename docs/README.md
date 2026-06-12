# 📚 Documentação Técnica — Search+ (Entrega N2)

Esta pasta reúne os artefatos de modelagem e documentação exigidos para a N2.
Abordagem da equipe: **SQL (PostgreSQL/Supabase)**.

## Índice dos artefatos

| Arquivo | Entrega do professor |
|---|---|
| [`01-casos-de-uso.puml`](01-casos-de-uso.puml) | ✅ Diagrama de Casos de Uso refinado |
| [`02-sequencia-login.puml`](02-sequencia-login.puml) | ✅ Diagrama de Sequência — Login |
| [`03-sequencia-crud-colecoes.puml`](03-sequencia-crud-colecoes.puml) | ✅ Diagrama de Sequência — CRUD |
| [`04-der.puml`](04-der.puml) | ✅ DER (SQL) |
| [`05-modelagem-dados-DER-ORM.md`](05-modelagem-dados-DER-ORM.md) | ✅ DER + ORM explicado |
| [`06-dossie-tecnico-sprints.md`](06-dossie-tecnico-sprints.md) | ✅ Dossiê Técnico de Sprint (1 e 2) |
| [`../backend/schema.sql`](../backend/schema.sql) | DDL real do banco (base do DER) |

## Como visualizar os diagramas (.puml)

Os diagramas estão em **PlantUML** (texto → imagem; versiona bem no Git). Para ver:
1. **Online:** copie o conteúdo do `.puml` e cole em https://www.plantuml.com/plantuml
2. **VS Code:** instale a extensão "PlantUML" e use Alt+D para pré-visualizar.

## Mapa das 7 entregas da N2

| # | Entrega | Situação |
|---|---|---|
| 1 | Diagrama de Sequência atualizado | ✅ Login + CRUD |
| 2 | Diagrama de Casos de Uso refinado | ✅ |
| 3 | DER + ORM (SQL) | ✅ DER + doc da camada de dados |
| 4 | Modelagem Mongoose/NoSQL | ➖ Não se aplica (abordagem é SQL) |
| 5 | JSON + LocalStorage (Sem Banco) | ➖ Não se aplica (abordagem é SQL) |
| 6 | Código (Front+Back+BD) rodando | ✅ Ver instruções abaixo |
| 7 | Organização Git (main/develop/feature) | ✅ Ver `07-git-fluxo.md` |

> Itens 4 e 5 são trilhas de **outras abordagens**. O enunciado pede que cada
> equipe atualize "conforme **sua** abordagem" — a nossa é SQL (item 3).

## Como rodar o sistema (para a apresentação da N2)

1. Ter **Python 3.10+** e **Ollama** instalados (com `llava` e `llama3.2`).
2. Configurar `backend/.env` com as credenciais do Supabase (ver `.env.example`).
3. Clicar em **`rodar.bat`** (ou `py backend/app.py`).
4. Acessar `http://127.0.0.1:5000`.

Detalhes técnicos completos: [`../RELATORIO.txt`](../RELATORIO.txt).
