# Testes, carga e CI do Search+

Guia para rodar e manter a suíte. Os comandos aqui são os mesmos que o CI
executa — se passa local, passa no pipeline.

---

## Ferramentas

| Para quê | Ferramenta | Por que esta |
|---|---|---|
| Testes | **pytest** + **pytest-cov** | Padrão da stack Python; o projeto não usa Node |
| Lint e formatação | **ruff** | Binário único, rápido, substitui flake8 + black |
| Carga | **Locust** | Python puro, instalável por pip — k6 exigiria binário externo e Artillery exigiria Node, que o projeto não tem |
| Tipos | **mypy** (informativo) | O código não usa type hints de forma sistemática |
| CI | **GitHub Actions** | O repositório já está no GitHub |

## Pré-requisitos

- Python 3.11+ (`py` no Windows, `python3` no Linux/macOS)
- Nada além disso para a suíte principal: os testes **não** precisam de
  Postgres, dos modelos de IA nem de chave da Anthropic

```bash
py -m pip install -r requirements-dev.txt
```

Se ainda não tiver as dependências da aplicação:

```bash
py -m pip install -r backend/requirements.txt
```

---

## Rodando

Tudo passa por `dev.py`, que embrulha os comandos com as mesmas opções do CI:

```bash
py dev.py testes
```

| Comando | O que faz |
|---|---|
| `py dev.py testes` | Unitários + integração (sem banco) |
| `py dev.py unitarios` | Só os unitários — mais rápido |
| `py dev.py integracao` | Só os de integração, contra o mock |
| `py dev.py banco` | Os que exigem Postgres com pgvector |
| `py dev.py cobertura` | Testes + relatório HTML |
| `py dev.py observar` | Re-executa a cada alteração de arquivo |
| `py dev.py lint` | Lint e formatação |
| `py dev.py formatar` | Aplica o formatador |
| `py dev.py tipos` | Verificação de tipos (informativa) |
| `py dev.py build` | Compila os módulos e confere o frontend |
| `py dev.py ci` | Tudo que o CI roda, na ordem |

Direto pelo pytest, quando precisar de controle fino:

```bash
py -m pytest tests -m unit -q
```

```bash
py -m pytest tests/unit/test_ajuste_score.py -v
```

```bash
py -m pytest tests -k "caminho or prefixo" -v
```

### Como a suíte roda sem infraestrutura

`backend/app.py` faz três coisas no import que impediriam testes rápidos:
levanta erro sem `DATABASE_URL`, abre um pool real de Postgres e carrega ~1 GB
de modelos. `tests/conftest.py` neutraliza as três antes do import — aponta a
URL para um DSN que nunca é discado, troca o construtor do pool por um duplo e
substitui `sentence_transformers` por um stub que falha ao instanciar, caindo no
`try/except` que o próprio app já tem.

O backend **não foi alterado** para isso. Efeito colateral útil: a suíte roda
com `SBERT_OK=False` e `CLIP_OK=False`, exercitando o caminho degradado — que é
como o app se comporta quando um modelo não carrega em produção.

---

## Cobertura

```bash
py dev.py cobertura
```

Abre `htmlcov/index.html` para navegar linha a linha. O piso configurado é
**43%** e a suíte mede **45%**.

Não é 70% por um motivo concreto, não por preguiça: `backend/app.py` tem ~3.400
linhas e cerca de metade é I/O que só executa com infraestrutura real.

**Coberto** — a lógica que decide o comportamento do produto:

| Área | O que se verifica |
|---|---|
| Regras de score | Rejeições (pessoa/animal/gênero), reforços, estilo foto vs. desenho |
| Análise da consulta | Detecção de intenção, expansão de sinônimos, stopwords |
| Descrição da IA | Parsing dos campos, categorias, texto do embedding |
| Caminhos de pasta | Prefixo, caixa, subpasta, pasta irmã |
| Autenticação | bcrypt, migração de SHA-256, limite de 72 bytes |
| Servir estáticos | Allowlist, dotfiles, traversal |
| Endpoints de dados | Painel, galeria, favoritos, coleções, histórico |
| Extração de texto | TXT/CSV/PDF/DOCX, arquivo corrompido, byte NUL |

**Não coberto**, e o que seria preciso:

| Área | Por que está fora |
|---|---|
| `api_search` completo (~250 linhas) | Precisa de SBERT, CLIP, pgvector e da API da Anthropic ao mesmo tempo |
| `_rerank_com_claude` | Chamada paga; mockar a resposta testaria o mock, não o julgamento |
| `_process_worker` | Loop infinito em thread; testável só com refatoração do backend |
| Geração de embeddings | Exige os modelos de 1 GB carregados |
| Diálogos do tkinter | Abrem janela nativa do Windows |
| Pool de conexões | Precisa de Postgres real (parcialmente coberto em `requires_db`) |

Suba o piso quando a cobertura subir de verdade. Não fabrique teste para mover a
porcentagem — cobertura alta com teste vazio é pior que cobertura honesta.

---

## Testes com Postgres

Ficam atrás do marker `requires_db` e são **pulados** por padrão. Só rodam com
`SEARCHPLUS_TEST_DATABASE_URL` apontando para um banco **dedicado a testes**:
eles criam e apagam linhas.

Há uma trava: se essa URL for igual à `DATABASE_URL` da aplicação, a suíte falha
de propósito, em vez de escrever no banco de produção.

```bash
docker run --rm -p 5433:5432 -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=searchplus_test pgvector/pgvector:pg16
```

```bash
SEARCHPLUS_TEST_DATABASE_URL=postgresql://postgres:teste@localhost:5433/searchplus_test py dev.py banco
```

No CI isso é automático: um service container `pgvector/pgvector:pg16` sobe e
morre com o job.

---

## Testes de carga

Três perfis, escolhidos por `SEARCHPLUS_LOAD_PROFILE`:

| Perfil | Forma | Quando usar |
|---|---|---|
| `smoke` | 5 usuários, 30s | Verificar que o script e o alvo funcionam. Roda no CI |
| `load` | Sobe a 20, sustenta, desce (~3 min) | Simular uso normal com pico moderado |
| `stress` | Sobe até 150 em degraus (~2,5 min) | Achar o ponto de degradação. **Manual, sob supervisão** |

O alvo padrão é o **mock** na porta 5001 — sem Postgres, sem modelo e sem
chamada paga:

```bash
py dev.py mock
```

```bash
py dev.py smoke
```

Contra o backend real (porta 5000), a carga mede o motor de verdade — inclusive
as chamadas ao Claude, **que custam dinheiro**:

```bash
SEARCHPLUS_LOAD_URL=http://127.0.0.1:5000 py dev.py smoke
```

### Segurança

O script **recusa** qualquer host que não seja localhost. Para um ambiente de
teste dedicado remoto, é preciso declarar a intenção com
`SEARCHPLUS_LOAD_ALLOW_REMOTE=1`. **Nunca aponte para produção.**

O perfil `stress` pede confirmação antes de começar.

### Metas de desempenho

Referências iniciais, ajustáveis por variável de ambiente:

| Métrica | Limite | Variável |
|---|---|---|
| Taxa de erro | < 1% | `SEARCHPLUS_LOAD_MAX_ERROR_RATE` |
| p95 geral | < 1000 ms | `SEARCHPLUS_LOAD_MAX_P95_MS` |
| p95 de endpoints com IA | < 5000 ms | `SEARCHPLUS_LOAD_MAX_P95_IA_MS` |

Endpoints com IA (`/api/search`, `/api/search_by_image`) têm limite maior porque
uma busca no backend real pode chamar o Claude duas vezes: para descrever
imagens sob demanda e para re-ranquear.

Violar qualquer limite encerra o Locust com código 1 — o CI quebra.

**Calibre contra o backend real antes de tratar como meta.** Os números atuais
foram validados contra o mock, cujo `/api/search` responde em ~250 ms. O backend
real é mais lento: na medição desta sessão, a primeira busca de uma imagem sem
descrição levou 38 s (chamando o Claude) e as seguintes, 2 a 4 s com o cache
quente. Ou seja: o limite de 5 s para IA cobre o caso cacheado, **não** a
primeira descrição. Se for medir o backend real com acervo frio, suba
`SEARCHPLUS_LOAD_MAX_P95_IA_MS` e registre o motivo.

---

## CI/CD

`.github/workflows/ci.yml`. Dispara em pull request, push na `main` e execução
manual (botão "Run workflow").

| Job | O que faz | Barra a entrega? |
|---|---|---|
| `qualidade` | Lint e formatação dos testes | Sim |
| | Lint do backend | Não — informativo |
| `testes` | Unitários + integração + cobertura | Sim |
| `testes-com-banco` | Integração com Postgres efêmero | Não bloqueia o portão |
| `build` | Compila os módulos, confere o frontend | Sim |
| | Verificação de tipos | Não — informativo |
| `carga-smoke` | Smoke contra o mock | Sim |
| `portao` | Agrega os anteriores | — |

`portao` existe para que a proteção de branch precise exigir **um** check só.

O lint do backend é informativo de propósito: `backend/` é compartilhado com
produção e o `AGENTS.md` pede que não seja alterado por conveniência. Os 11
achados atuais são pré-existentes; quem abre uma PR de frontend não deveria ser
barrado por eles. Ao corrigi-los, promova o passo a bloqueante.

### Artefatos

`relatorios-de-teste` (JUnit XML, coverage XML, HTML navegável) e
`relatorio-de-carga` (HTML do Locust), retidos por 14 dias.

### Secrets

**Nenhum secret é necessário hoje.** A suíte não fala com Supabase nem com a
Anthropic. Quando isso mudar, registre em *Settings → Secrets and variables →
Actions* e referencie com `${{ secrets.NOME }}` — nunca escreva o valor no YAML.

| Secret | Quando precisará |
|---|---|
| `SEARCHPLUS_TEST_DATABASE_URL` | Se trocar o container efêmero por um banco de teste gerenciado |
| `ANTHROPIC_API_KEY` | Se algum dia houver teste que exercite o Claude de verdade (custa por execução) |

### Deploy

Não há deploy no pipeline, porque **não existe infraestrutura de deploy definida
neste repositório** — nenhum Dockerfile, nenhuma configuração de servidor,
nenhum destino. Inventar um seria pior que não ter.

O que precisa existir antes: destino definido (VPS, container, PaaS), forma de
publicar (imagem, `rsync`, integração da plataforma), e as credenciais como
secrets. Com isso, um job `deploy` com `needs: [portao]` e
`if: github.ref == 'refs/heads/main'` encaixa no final do arquivo — os gates de
qualidade já estão prontos para segurá-lo.

---

## Variáveis de ambiente

Nenhuma é obrigatória para rodar os testes. Todas em `.env.example`.

| Variável | Para quê | Padrão |
|---|---|---|
| `SEARCHPLUS_TEST_DATABASE_URL` | Banco de teste dos `requires_db` | vazio → testes pulados |
| `SEARCHPLUS_LOAD_URL` | Alvo da carga | `http://127.0.0.1:5001` |
| `SEARCHPLUS_LOAD_PROFILE` | `smoke`, `load` ou `stress` | `smoke` |
| `SEARCHPLUS_LOAD_USER` / `_PASSWORD` | Credencial de carga | `carga_teste` |
| `SEARCHPLUS_LOAD_ALLOW_REMOTE` | Libera alvo não-local | não definida |
| `SEARCHPLUS_LOAD_MAX_ERROR_RATE` | Limite de erro | `0.01` |
| `SEARCHPLUS_LOAD_MAX_P95_MS` | Limite de p95 | `1000` |
| `SEARCHPLUS_LOAD_MAX_P95_IA_MS` | Limite de p95 com IA | `5000` |

---

## Manutenção

**Ao adicionar um endpoint:** implemente em `app.py`, replique em
`mock_server.py`, documente em `docs/API.md`. `test_paridade_mock.py` verifica os
três — e falha se um ficar para trás.

**Ao mudar o formato da descrição da IA:** `test_descricao_ia.py` vai quebrar.
É o alarme funcionando: `_extrair_campos_descricao`, `_campo_descricao` e
`_categorias_do_arquivo` leem esse formato.

**Ao mexer em caminho de pasta:** rode `tests/unit/test_caminhos_pasta.py`. Ali
estão fixados três defeitos distintos que já aconteceram — vazamento para pasta
irmã, duplicata por caixa e exclusão levando subpasta junto.

### Próximos testes recomendados

1. **`api_search` de ponta a ponta**, com Postgres semeado e o cliente da
   Anthropic dublado no limite da rede. É a maior lacuna de cobertura.
2. **`_process_worker`**, extraindo o corpo do loop para uma função testável.
   Já morreu em produção por causa de um byte NUL.
3. **Frontend.** `script.js` tem ~2.700 linhas sem teste nenhum. Vitest com
   jsdom cobriria `renderizarResultados()` e os mapas de categoria — mas
   introduz Node num projeto que hoje não depende dele; decida conscientemente.
4. **Concorrência do pool** sob carga, para achar o limite real de `DB_POOL_MAX`.
5. **Regressão de ranking**: um conjunto fixo de consultas com resultado
   esperado, medindo se uma mudança no prompt melhora ou piora a busca.
