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

## Guias de desenvolvimento

| Arquivo | Conteúdo |
|---|---|
| [`API.md`](API.md) | Contrato da API: payload, resposta e erros de cada endpoint |
| [`FRONTEND.md`](FRONTEND.md) | Guia para substituir a camada visual (inclui o servidor mock) |
| [`TESTING.md`](TESTING.md) | Suíte de testes, testes de carga e CI |

## Notas técnicas e especificações

Documentos fora do escopo da N2, produzidos ao longo do desenvolvimento.

| Arquivo | Conteúdo |
|---|---|
| [`07-git-fluxo.md`](07-git-fluxo.md) | Convenção de branches (`main` / `develop` / `feature/*`) |
| [`08-correcoes-conexao-e-busca.md`](08-correcoes-conexao-e-busca.md) | Correções: pooler do Supabase e busca visual (CLIP) |
| [`09-requisitos-funcionais.md`](09-requisitos-funcionais.md) | RF-001 … RF-335 e os critérios de aceite |
| [`10-requisitos-nao-funcionais.md`](10-requisitos-nao-funcionais.md) | RNF-001 … RNF-090 + resultado da carga + débitos preexistentes |
| [`features/11-limpar-busca.md`](features/11-limpar-busca.md) | Botão `×` para limpar o campo de busca |
| [`features/12-colecoes-exportacao.md`](features/12-colecoes-exportacao.md) | Seleção, coleções e exportação para pasta local |
| [`features/13-selecao-em-massa.md`](features/13-selecao-em-massa.md) | Selecionar tudo e exportação imediata da coleção |
| [`features/14-pasta-vinculada.md`](features/14-pasta-vinculada.md) | Coleção espelhada numa pasta do computador |

## Relatórios de entrega

Relatório em Word, com capa, escrito em linguagem simples: o que foi feito e
o que mudou para quem usa o app. Cada rodada gera um arquivo novo, com data no
nome, para ficar o histórico do que já tinha sido entregue em cada momento.

```bash
py tools/gerar_relatorio.py
```

Sai nos dois formatos: o `.docx` para editar, o `.pdf` para enviar.

| Data | Word | PDF |
|---|---|---|
| 31/08/2026 | [`.docx`](SearchPlus_Implementacoes_2026-08-31.docx) | [`.pdf`](SearchPlus_Implementacoes_2026-08-31.pdf) |

O conteúdo do relatório vive em `tools/gerar_relatorio.py`, e não num .docx
editado à mão: assim o texto entra em revisão de código como o resto, e a
versão seguinte parte da anterior em vez de recomeçar.

O PDF sai do Word quando ele está instalado, e do LibreOffice quando não
está. Sem nenhum dos dois, o `.docx` é gerado do mesmo jeito e o script
avisa — a entrega não depende do conversor.

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
