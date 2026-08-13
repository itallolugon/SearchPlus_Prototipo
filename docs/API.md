# Search+ — Contrato da API

Referência dos endpoints do backend (`backend/app.py`) para quem está construindo o frontend.

- **Base URL padrão:** `http://127.0.0.1:5000`
- **Formato:** JSON em todo request e response (`Content-Type: application/json`)
- **Autenticação:** cookie de sessão — leia [Autenticação](#autenticação) antes de escrever a primeira chamada
- **Servidor mock:** `py backend/mock_server.py` sobe a API inteira com dados fictícios em `http://127.0.0.1:5001`, sem banco, sem modelos de IA e sem chave de API. Use-o para desenvolver sem depender da infra.

---

## Sumário

- [Começando](#começando)
- [Autenticação](#autenticação)
- [Convenções](#convenções)
- [Objetos comuns](#objetos-comuns)
- [Endpoints](#endpoints)
  - [Sessão](#sessão)
  - [Configuração do usuário](#configuração-do-usuário)
  - [Pastas monitoradas](#pastas-monitoradas)
  - [Busca](#busca)
  - [Home: estatísticas e galeria](#home-estatísticas-e-galeria)
  - [Favoritos](#favoritos)
  - [Coleções](#coleções)
  - [Histórico de buscas](#histórico-de-buscas)
  - [Arquivos](#arquivos)
  - [Motor de indexação](#motor-de-indexação)
- [Particularidades que afetam o frontend](#particularidades-que-afetam-o-frontend)

---

## Começando

```bash
# API real (precisa de backend/.env com DATABASE_URL)
py backend/app.py          # http://127.0.0.1:5000

# API mock (não precisa de nada)
py backend/mock_server.py  # http://127.0.0.1:5001
```

No mock, **qualquer usuário e senha são aceitos** no login.

### Rodando o front num dev server separado

O Flask serve o frontend por padrão, então o cenário mais simples é same-origin. Se preferir rodar Vite/Next/Angular à parte, configure em `backend/.env`:

```ini
ALLOWED_ORIGINS=http://localhost:5173
```

As portas de dev mais comuns (5173, 3000, 4200, 8080, 5500) já vêm liberadas por padrão — só mexa nessa variável se usar outra.

⚠️ **Cookies cross-origin exigem HTTPS.** Veja [Autenticação](#autenticação).

### Entregando o front pronto

Quando o build estiver pronto, aponte o backend para ele — nenhuma linha de Python muda:

```ini
FRONTEND_DIR=../front/dist
```

O Flask passa a servir esse diretório, com fallback para `index.html` em rotas desconhecidas (necessário para SPAs com roteamento próprio).

---

## Autenticação

Sessão via **cookie** (`Set-Cookie` no login, `HttpOnly`). Não há JWT nem header `Authorization`.

**Toda requisição precisa enviar o cookie.** Em `fetch`, isso não é o padrão:

```js
fetch("/api/search", {
  method: "POST",
  credentials: "include",              // ← obrigatório
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "cachorro", filtro: "all" }),
});
```

Em axios: `axios.defaults.withCredentials = true`.

Sem `credentials: "include"` toda chamada volta **401**, inclusive logo após um login bem-sucedido.

### Same-origin vs. cross-origin

| Cenário | Config no `.env` | Observação |
|---|---|---|
| Flask serve o front (mesma porta) | nada a fazer | `SameSite=Lax`, mais seguro. **Recomendado.** |
| Front em outra porta/domínio | `CROSS_SITE_COOKIES=1` | Vira `SameSite=None; Secure` — **só funciona sob HTTPS** |

O detalhe que costuma custar meia manhã de debug: `localhost:5173` e `localhost:5000` são *sites diferentes* para a regra de cookies. Com `SameSite=Lax` (padrão), o browser silenciosamente não envia o cookie e todas as chamadas voltam 401 mesmo com o login tendo funcionado. Se precisar de portas separadas em `http://`, a saída prática é o **proxy do dev server** (`server.proxy` no Vite, `proxy` no CRA), que mantém tudo same-origin e dispensa `CROSS_SITE_COOKIES`.

---

## Convenções

**Erros** vêm com o status HTTP correspondente e um corpo JSON. A chave varia por endpoint — trate as duas:

```json
{ "error": "Não autenticado." }
{ "mensagem": "Usuário ou senha incorretos." }
```

| Status | Quando |
|---|---|
| `200` | Sucesso |
| `400` | Payload inválido ou campo obrigatório faltando |
| `401` | Sem sessão ativa |
| `403` | Arquivo fora das pastas monitoradas |
| `404` | Recurso não encontrado |
| `409` | Conflito (usuário ou coleção já existe) |
| `503` | Schema restaurado; a resposta traz `"retry": true` — vale repetir a chamada |

**Sucesso** normalmente traz `{"status": "ok"}`, às vezes com dados extras.

---

## Objetos comuns

### Arquivo

Formato usado em busca, favoritos, coleções e galeria — sempre o mesmo:

```json
{
  "id": 42,
  "nome": "cachorro-parque.jpg",
  "caminho": "C:\\Users\\Demo\\Imagens\\cachorro-parque.jpg",
  "tipo": "jpg",
  "descricao_ia": "- Estilo: fotografia\n- O que é: cachorro correndo...",
  "conteudo": "(igual a descricao_ia — campo legado)",
  "trecho": "(primeiros ~200 caracteres, para preview)",
  "data": "2026-08-10T19:32:58.960360",
  "favorito": false,
  "score": 0.95
}
```

| Campo | Notas |
|---|---|
| `caminho` | Caminho **absoluto no Windows**, com `\` — precisa de encode para virar URL |
| `tipo` | Extensão sem ponto (`jpg`, `pdf`, `mp4`) |
| `descricao_ia` | **Pode vir vazio** em imagens — veja [indexação lazy](#indexação-lazy) |
| `score` | `0.0`–`1.0`. O front atual separa "Melhores" (≥ 0.60) de "Semânticos" |

### Descrição de imagem

Quando preenchida, segue um layout fixo de campos:

```
- Estilo: desenho, ilustração, cartoon
- O que é: ...
- Pessoas: ...        (ou 'nenhuma')
- Animais: ...        (ou 'nenhum')
- Objetos: ...
- Ambiente: ...
- Ações: ...
- Texto: ...          (ou 'nenhum')
- Tags: ...
```

Documentos não usam esse formato — trazem o texto extraído direto.

### Categorias

Chaves fixas em `/api/stats` e `/api/gallery`: `pessoas`, `animais`, `comida`, `natureza`, `urbano`, `desenhos`, e `outras` (só na galeria).

Mantenha um rótulo de fallback: se o backend ganhar uma categoria nova, ela chega antes de o front conhecê-la.

---

## Endpoints

### Sessão

#### `POST /api/login`
```json
{ "username": "demo", "password": "123" }
```
→ `200` `{"status": "ok", "username": "demo"}` · `400` campos vazios · `401` credenciais inválidas

#### `POST /api/register`
```json
{ "username": "demo", "handle": "demo", "password": "123" }
```
→ `200` `{"status": "ok"}` · `409` usuário já existe

`POST /api/cadastro` é um alias idêntico.

#### `GET /api/check_session`
→ `200` `{"username": "demo"}` · `401` sem sessão

Chame no boot do app para decidir entre tela de login e app.

#### `POST /api/logout`
→ `200` `{"status": "ok"}`

---

### Configuração do usuário

#### `GET /api/config`

Devolve as preferências **e** as pastas monitoradas. Funciona sem login (retorna os padrões), para o front aplicar tema e cores antes da tela de login.

```json
{
  "perfil_nome": "Usuário Demo",
  "perfil_handle": "demo",
  "perfil_bio": "", "perfil_cargo": "", "perfil_local": "",
  "perfil_avatar": "", "perfil_banner": "",
  "cor_primaria": "#A855F7", "cor_secundaria": "#E879F9", "cor_texto_botao": "#FFFFFF",
  "tema": "dark",
  "bg_url": "", "bg_blur": 15,
  "idioma": "pt-BR",
  "notificacoes": true,
  "atalho_busca": "Ctrl+Shift+F",
  "iniciar_sistema": false,
  "modo_privado": false,
  "pastas_ignoradas": "",
  "modo_desempenho": "economico",
  "pastas": [],
  "historico_pastas": false
}
```

#### `POST /api/config`

Salva preferências. **Merge parcial** — envie só os campos que mudaram; os demais são preservados.

```json
{ "tema": "light", "cor_primaria": "#3B82F6" }
```
→ `200` `{"status": "ok"}`

`pastas` e `historico_pastas` são ignorados no POST (são derivados; use `/api/folders`).

---

### Pastas monitoradas

#### `GET /api/folders`
```json
{
  "pastas": [
    {
      "id": 1,
      "path": "C:\\Users\\Demo\\Imagens",
      "prioridades": ["tudo"],
      "perfil_analise": "fast",
      "janela_processamento": "always"
    }
  ]
}
```

#### `POST /api/folders`
```json
{
  "pasta": "C:\\Users\\Demo\\Imagens",
  "prioridades": ["tudo"],
  "perfil_analise": "fast",
  "janela_processamento": "always"
}
```
→ `200` `{"status": "ok", "pastas": [...]}` · `400` caminho inexistente

**A indexação não começa aqui** — só registra a pasta. Dispare com `POST /api/analyze_folders` depois que o usuário confirmar.

Repetir o POST na mesma pasta atualiza a configuração dela.

#### `DELETE /api/folders`
```json
{ "pasta": "C:\\Users\\Demo\\Imagens" }
```
Remove a pasta **e os arquivos dela** do índice.

#### `DELETE /api/folders/<id>`
Mesma coisa, por ID.

#### `POST /api/folders/update_config`
```json
{ "id": 1, "perfil_analise": "deep" }
```
Aceita `id` **ou** `path` para identificar a pasta. Campos alteráveis: `prioridades`, `perfil_analise` (`fast`/`deep`), `janela_processamento`.

#### `GET /api/estimate_time?pasta=<path>&perfil=fast&foco=tudo`
```json
{ "estimativa_minutos": 3, "total_imagens": 120 }
```

---

### Busca

#### `POST /api/search`

O endpoint principal.

```json
{
  "query": "cachorro no parque",
  "filtro": "all",
  "avancado": {
    "data_de": "2026-01-01",
    "data_ate": "2026-08-13",
    "pasta": "C:\\Users\\Demo\\Imagens",
    "tam_min": 0.1,
    "tam_max": 50
  }
}
```

| Campo | Valores |
|---|---|
| `query` | Texto da busca. Vazio → `{"resultados": [], "tempo": 0}` |
| `filtro` | `all` \| `imagem` \| `documento` \| `midia` |
| `avancado` | Opcional. Datas em `YYYY-MM-DD`; tamanhos em **MB** |

```json
{ "resultados": [ /* array de Arquivo */ ], "tempo": 1.84 }
```

Máximo de 60 resultados. Já vêm ordenados por `score` decrescente; itens com score ≤ 0.25 são cortados.

Se a busca semântica estiver indisponível, a resposta ainda é `200`, mas com um campo `erro`:
```json
{ "resultados": [], "tempo": 0, "erro": "SBERT indisponível — busca semântica desligada." }
```

> ⏱️ **Latência:** de 1 a 8 segundos na API real. A busca é síncrona e pode chamar o modelo de IA duas vezes (descrever imagens novas + reordenar). **Projete um estado de carregamento decente** — não é uma chamada de 200ms. O mock simula ~250ms.

`GET /api/search?q=<texto>&filtro=<filtro>` existe para testes rápidos, sem filtros avançados.

#### `POST /api/search_by_image`

Busca por similaridade visual. Envie **um** dos dois:

```json
{ "data_url": "data:image/jpeg;base64,..." }
{ "file_id": 42 }
```
```json
{ "resultados": [ /* Arquivo */ ], "tempo": 0.31, "modo": "imagem" }
```

---

### Home: estatísticas e galeria

#### `GET /api/stats`
```json
{
  "total_arquivos": 12,
  "total_pastas": 2,
  "por_formato": { "imagem": 9, "documento": 2, "midia": 1 },
  "por_categoria": [
    { "categoria": "pessoas", "total": 2 },
    { "categoria": "animais", "total": 2 }
  ]
}
```
`por_categoria` já vem ordenado (maior primeiro) e omite categorias zeradas.

#### `GET /api/gallery`
```json
{
  "grupos": [
    { "categoria": "animais", "total": 2, "itens": [ /* Arquivo */ ] }
  ],
  "total_imagens": 9
}
```
Só imagens. **Um arquivo pode aparecer em mais de um grupo** (um desenho de cachorro entra em `animais` e `desenhos`) — não assuma unicidade ao montar a grade.

---

### Favoritos

#### `GET /api/favorites`
```json
{ "resultados": [ /* Arquivo */ ] }
```
Sem sessão devolve `200` com lista vazia (não 401).

#### `POST /api/favorites/toggle`
```json
{ "id": 42 }
```
→ `{"status": "sucesso", "favorito": true}` · `404` arquivo não encontrado

---

### Coleções

#### `GET /api/collections`
```json
{
  "colecoes": [
    {
      "id": 1,
      "nome": "Favoritos do mês",
      "total": 3,
      "criado_em": "2026-08-13T19:32:58",
      "capas": ["C:\\...\\a.jpg", "C:\\...\\b.jpg"]
    }
  ]
}
```
`capas` traz até 4 caminhos de imagem, para montar a capa em mosaico.

#### `POST /api/collections`
```json
{ "nome": "Viagem 2026" }
```
→ `{"status": "ok", "id": 3, "nome": "Viagem 2026"}` · `400` nome vazio · `409` nome duplicado

#### `GET /api/collections/<id>`
→ `{"resultados": [ /* Arquivo */ ]}` · `404`

#### `DELETE /api/collections/<id>`
→ `{"status": "ok"}`

#### `POST` / `DELETE /api/collections/<id>/files`
```json
{ "file_id": 42 }
```
→ `{"status": "ok", "acao": "adicionado"}` ou `"removido"`

Adicionar duas vezes é idempotente (não duplica, não dá erro).

---

### Histórico de buscas

#### `GET /api/search_history`
```json
{ "historico": ["cachorro no parque", "pôr do sol"] }
```
Mais recente primeiro, no máximo 10. Sem sessão devolve lista vazia com `200`.

#### `POST /api/search_history`
```json
{ "query": "cachorro no parque" }
```
Repetir um termo existente o move para o topo em vez de duplicar.

#### `DELETE /api/search_history/<index>`
Remove por **índice** (0 = mais recente), não por ID.

#### `POST /api/clear_history`
→ `{"status": "ok", "historico": []}`

---

### Arquivos

#### `GET /api/file/<caminho>`

Serve o binário do arquivo (para `<img src>`, preview, download).

O caminho é absoluto e do Windows — precisa ser encodado:

```js
const url = `/api/file/${encodeURIComponent(arquivo.caminho)}`;
```

→ binário com o `Content-Type` correto · `401` · `403` fora das pastas monitoradas · `404`

O `403` é proposital: só arquivos dentro das pastas monitoradas do próprio usuário são servidos.

#### `GET /api/open_location?caminho=<path>`

Abre o Explorer do Windows com o arquivo selecionado. Roda **no servidor**.

#### `GET /api/choose_folder` · `GET /api/choose_image`

```json
{ "status": "sucesso", "pasta": "C:\\Users\\Demo\\Downloads" }
{ "status": "sucesso", "caminho": "...", "data_url": "data:image/png;base64,..." }
{ "status": "cancelado" }
```

> ⚠️ **Abrem uma janela nativa do Windows no computador que roda o servidor.** Se o backend estiver em outra máquina (ou num container), o diálogo aparece lá — e a requisição fica pendurada até alguém interagir com ela. Sempre ofereça um caminho alternativo na interface: um `<input type="file">` para imagens e um campo de texto para colar o caminho da pasta.

---

### Motor de indexação

#### `GET /api/status`
```json
{ "status": "Ocioso", "arquivos_pendentes": 0, "arquivos_processados_sessao": 12 }
```
`status` é texto livre para exibição (`"Ocioso"`, `"Processando..."`). Use enquanto houver indexação em curso — o front atual consulta a cada poucos segundos.

#### `POST /api/analyze_folders`
Dispara a varredura de todas as pastas. Responde na hora; o trabalho roda em background — acompanhe por `/api/status`.
```json
{ "status": "ok", "mensagem": "2 pasta(s) sendo analisadas." }
```

#### `POST /api/reanalyze`
Re-enfileira arquivos com falha e limpa descrições geradas por uma versão antiga do prompt.
```json
{ "status": "ok", "reenfileirados": 3, "descricoes_limpas": 12 }
```

#### `POST /api/reembed`
Regenera embeddings sem redescrever imagens (não gasta API de IA). `atualizados` é o total que será varrido em background, não o que já terminou.

#### `POST /api/cancel_analysis`
Esvazia a fila. O arquivo em processamento no momento termina.
```json
{ "status": "ok", "descartados": 14 }
```

#### `POST /api/clear_cache`
Limpa o índice do usuário.

#### `GET /api/debug/files` · `GET /api/debug/scores?q=<query>`
Inspeção durante o desenvolvimento: lista os arquivos indexados e detalha a composição do score de cada resultado. Úteis para entender por que algo apareceu (ou não) numa busca.

---

## Particularidades que afetam o frontend

### Indexação lazy

Imagens são indexadas **sem descrição**. Ao adicionar uma pasta, o backend gera apenas o embedding visual local — rápido e sem custo de API. A descrição é escrita sob demanda, durante a busca, para as poucas imagens mais relevantes, e fica em cache dali em diante.

Consequência prática: **`descricao_ia` vazio é um estado normal, não um erro.** Uma imagem recém-indexada aparece na galeria sem texto e ganha descrição depois que alguma busca a alcança. Não mostre "erro ao processar" nesse caso.

### Caminhos do Windows

`caminho` vem com barras invertidas (`C:\Users\...`). Ao montar URLs, use `encodeURIComponent`. Em JSON eles chegam escapados (`C:\\Users\\...`) — `JSON.parse` resolve isso sozinho.

### Latência da busca

De 1 a 8 segundos na API real, contra ~250ms no mock. Vale um skeleton ou barra de progresso, e desabilitar o botão durante a chamada. Se a IA falhar, a busca **não** quebra: retorna com a ordenação do motor local.

### Paginação

Não existe. `/api/search` devolve no máximo 60 itens e `/api/gallery` devolve tudo de uma vez. Para acervos grandes, virtualize a lista no front.

### Recursos degradáveis

O servidor sobe mesmo sem seus componentes opcionais (modelos de IA, chave de API). Nesses casos a busca visual ou semântica fica desligada, e as respostas vêm vazias ou com o campo `erro` — sempre em `200`. Não trate ausência de resultados como falha de rede.
