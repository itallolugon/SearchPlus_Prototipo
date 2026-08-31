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
  "score": 0.95,
  "origem": "aparencia"
}
```

| Campo | Notas |
|---|---|
| `caminho` | Caminho **absoluto no Windows**, com `\` — precisa de encode para virar URL |
| `tipo` | Extensão sem ponto (`jpg`, `pdf`, `mp4`) |
| `descricao_ia` | **Pode vir vazio** em imagens — veja [indexação lazy](#indexação-lazy) |
| `score` | `0.0`–`1.0`. O front atual separa "Melhores" (≥ 0.60) de "Semânticos" |
| `origem` | Por que o resultado apareceu — veja abaixo |

#### `origem` — por que o resultado apareceu

O número que ordena a busca é exposto na API mas **fica escondido na
interface**, de propósito: "0,72" não ensina nada a ninguém. `origem` é a
explicação que entra no lugar dele — diz qual sinal mais contribuiu, o que
ensina o usuário a formular a próxima busca.

| Valor | O que a interface mostra | Quando acontece |
|---|---|---|
| `aparencia` | "pela aparência" | a imagem foi reconhecida pelo que aparece nela |
| `descricao` | "pelo que a imagem mostra" | bateu com a descrição escrita sobre a imagem |
| `texto` | "pelo texto do documento" | o termo está escrito dentro do arquivo |
| `nome` | "pelo nome do arquivo" | o nome contém o que foi digitado |

São quatro e não três porque, numa imagem, o texto que o Search+ tem não é
texto do arquivo — é a descrição gerada olhando para ela. Chamar isso de
"texto do documento" seria mentira sobre a origem do dado.

A escolha compara **contribuições já multiplicadas pelos pesos**, não os sinais
crus: um sinal visual alto que entra com peso baixo pode contribuir menos que
um textual médio com peso alto, e é a contribuição que explica a posição.

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
→ `200` `{"status": "ok"}` · `400` campo vazio ou senha acima de 72 bytes · `409` usuário já existe

A senha é limitada a **72 bytes** (limite do bcrypt). Conte em bytes, não em
caracteres: em UTF-8 cada letra acentuada ocupa 2, então "çã" × 40 já estoura.

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
  "ultima_pasta_exportacao": "",
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

#### `POST /api/folders/<id>/verificar`
Confere a pasta contra o disco e concilia o índice. Sem corpo.

```json
{
  "status": "ok",
  "pasta": "C:\\Users\\Demo\\Imagens",
  "novos": ["foto-nova.jpg"],
  "modificados": ["praia.jpg"],
  "ausentes": ["apagada.png"],
  "voltaram": [],
  "resumo": { "novos": 1, "modificados": 1, "ausentes": 1, "voltaram": 0 }
}
```

O que cada lista significa, e o que o servidor faz com ela:

| Lista | Situação | Efeito |
|---|---|---|
| `novos` | no disco, fora do índice | indexa e manda para a fila de análise |
| `modificados` | data ou tamanho mudaram | reindexa: a descrição antiga descrevia outro conteúdo |
| `ausentes` | no índice, sumiu do disco | **marca**, não apaga |
| `voltaram` | estava marcado como ausente e reapareceu | desmarca |

O arquivo ausente é marcado em vez de apagado porque o motivo mais comum de um
arquivo "sumir" é um disco externo desconectado. Apagar o registro jogaria fora
a descrição gerada pela IA e a participação do arquivo em coleções por causa de
um cabo solto.

A resposta é síncrona — quem clicou está esperando o número. Só a análise de
IA dos arquivos novos e modificados corre em segundo plano.

Erros:

- `404` — a pasta não é sua ou não existe mais no índice
- `409` com `"pasta_sumiu": true` — a pasta inteira não pôde ser aberta (movida,
  renomeada ou em disco desconectado). Nada é marcado nesse caso: seria a
  biblioteca inteira saindo da busca de uma vez.

#### `POST /api/folders/update_config`
```json
{ "id": 1, "perfil_analise": "deep" }
```
Aceita `id` **ou** `path` para identificar a pasta. Campos alteráveis: `prioridades`, `perfil_analise` (`fast`/`deep`), `janela_processamento`.

### Lixeira

Excluir uma coleção apagava trabalho que não volta: o agrupamento montado à mão
e o vínculo com as pastas geradas no disco. Agora a exclusão guarda um
**retrato** do que foi apagado, por 30 dias.

O retrato é um registro à parte, não uma marca de "excluído" na linha original.
Marcar exigiria `AND excluido_em IS NULL` em cada uma das ~22 consultas que leem
coleção, e esquecer uma não quebra nada de forma visível — ela só passa a
enxergar coleção excluída, e o usuário consegue adicionar foto a uma coleção que
está na lixeira. Com o retrato, a linha some de verdade e nenhuma consulta
precisa saber que a lixeira existe.

#### `GET /api/lixeira`
```json
{
  "dias": 30,
  "itens": [
    { "id": 4, "tipo": "colecao", "rotulo": "Viagem",
      "imagens": 12, "excluido_em": "2026-08-30T18:00:00+00:00" },
    { "id": 3, "tipo": "itens", "rotulo": "2 imagens de “Praia”",
      "imagens": 2, "excluido_em": "2026-08-30T17:55:00+00:00" }
  ]
}
```
Toda leitura da lixeira descarta antes o que passou dos 30 dias.

#### `POST /api/lixeira/<id>/restaurar`
Sem corpo. Recria o que foi apagado e tira o item da lixeira — nessa ordem: sair
da lixeira antes deixaria o usuário sem a coleção **e** sem o retrato dela.

A coleção volta com o **mesmo id**. Arquivo que o usuário apagou da biblioteca
nesse meio-tempo não volta; a coleção é restaurada sem ele, o que é melhor do
que falhar tudo por causa de uma foto.

Erros:

- `404` — o item não está mais na lixeira
- `409` — já existe outra coleção com esse nome, ou (para `tipo: "itens"`) a
  coleção de destino foi excluída depois

#### `DELETE /api/lixeira/<id>`
Descarta um item da lixeira de vez. Daqui não volta. `404` se já não estiver lá.

#### Onde o `lixeira_id` aparece

`DELETE /api/collections/<id>` e `DELETE /api/collections/<id>/files` passaram a
devolver `lixeira_id` — é o que o botão "desfazer" usa.

---

#### `GET /api/health`
Diz se o programa já está inteiro de pé. **Não exige sessão** — a espera
acontece justamente na tela de login, antes de qualquer sessão existir.

```json
{
  "servidor": "ok",
  "modelos": {
    "texto":  { "estado": "pronto", "motivo": "" },
    "visual": { "estado": "carregando", "motivo": "" }
  },
  "busca_pronta": true,
  "carregando": true
}
```

`estado` é `carregando`, `pronto` ou `indisponivel`; `motivo` só vem preenchido
em `indisponivel`. `busca_pronta` acompanha o modelo de **texto**, que é o que
destrava a busca escrita.

O servidor responde desde o primeiro instante e carrega os modelos em segundo
plano. Antes eles eram carregados na importação, e por ~30 segundos o navegador
não recebia nem a tela de login — o usuário via "não foi possível acessar" e
concluía que o programa não tinha aberto.

Enquanto `carregando` for `true`, `/api/search` e `/api/search_by_image`
respondem **503** com `"carregando": true` e uma mensagem pedindo para tentar
de novo em instantes. Depois que a carga termina, um 503 sem `carregando`
significa que o modelo não subiu e esperar não vai resolver.

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

#### `PATCH /api/collections/<id>`

Atualiza nome, pasta vinculada e modo de sincronia. Só toca os campos
presentes no corpo — mandar só `modo_sync` não desvincula a pasta.

```json
{ "nome": "Arquitetura Moderna",
  "pasta_vinculada": "D:\\Fotos\\Arquitetura Moderna",
  "modo_sync": "auto" }
```

→ `{"status": "ok", "id": 1, "nome": "…", "pasta_vinculada": "…", "modo_sync": "auto"}`
· `400` nome vazio, modo inválido, pasta inexistente ou corpo sem campos
· `404` · `409` nome duplicado

`modo_sync` aceita:

| Valor | O que acontece ao adicionar imagens à coleção |
|---|---|
| `auto` | Copia para a pasta vinculada na hora, sem perguntar |
| `perguntar` | Pergunta a cada adição |
| `manual` | Nunca copia sozinho; só pelo botão Exportar (padrão) |

Enviar `"pasta_vinculada": null` desvincula e devolve a coleção a `manual`.

#### `GET /api/collections/<id>/folders`

Pastas que o app gerou para esta coleção. Alimenta o botão "Abrir pasta
exportada" e o diálogo de exclusão.

```json
{ "pastas": [
    { "caminho": "D:\\Fotos\\Natureza", "nome": "Natureza",
      "existe": true, "vinculada": true, "arquivos": 12 }
] }
```

`vinculada` marca a pasta que recebe novas imagens. `existe` é `false` quando
o usuário apagou a pasta por fora — o registro fica, mas não há o que abrir.

#### `PATCH /api/collections/<id>/folders`

Troca o **complemento** do nome de uma pasta gerada. O prefixo continua sendo o
nome da coleção — é o que liga a pasta à coleção no Explorer.

```json
{ "caminho": "D:\\Fotos\\Ferias_backup", "sufixo": "praia" }
```

→ `{"status": "ok", "caminho": "D:\\Fotos\\Ferias_praia", "nome": "Ferias_praia", "sufixo": "praia"}`
· `400` sem `caminho` ou sem `sufixo` · `403` pasta não registrada · `404`
· `409` nome em uso, pasta em uso ou sumida

`sufixo` vazio deixa a pasta com só o nome da coleção. O valor é sanitizado
pelas mesmas regras do nome da pasta. **Nunca sobrescreve**: se já existir pasta
com o nome resultante, devolve 409 — mesclar duas em silêncio perderia arquivo.

#### `DELETE /api/collections/<id>/folders`

Apaga do disco as pastas escolhidas. **Irreversível — não há lixeira.**

```json
{ "caminhos": ["D:\\Fotos\\Natureza (1)"], "confirmar": true }
```

→ `{"status": "ok", "apagadas": ["…"], "falhas": []}`
· `400` sem `confirmar: true` ou sem `caminhos` · `404`

Três travas, todas obrigatórias:

| Trava | Efeito |
|---|---|
| Lista fechada | Só apaga caminho registrado para **esta** coleção e **este** usuário. Caminho arbitrário → `nao_autorizada` |
| Escolha explícita | `caminhos` é obrigatório; não existe "apagar todas" implícito |
| Confirmação | `confirmar: true` é obrigatório |

A coleção **não** é excluída por esta rota. São operações separadas: dá para
apagar a pasta e manter a coleção, e vice-versa. Apagar a pasta vinculada
desvincula a coleção e a devolve a `modo_sync: "manual"`.

#### `GET /api/collections/<id>/sync_status`

Compara a coleção com o conteúdo de cada pasta espelho. Responde a pergunta que
o modo `manual` deixa em aberto: **quais** imagens já foram copiadas e quais
ainda não.

```json
{
  "total_colecao": 5,
  "modo_sync": "manual",
  "pastas": [
    { "caminho": "D:\\Fotos\\Natureza", "nome": "Natureza",
      "existe": true, "recebe": true,
      "na_pasta": [ { "id": 1, "nome": "a.jpg" } ],
      "faltando": [ { "id": 2, "nome": "b.jpg" } ],
      "extras":   [ "antiga.jpg" ] }
  ]
}
```

| Lista | Significa |
|---|---|
| `na_pasta` | Está na coleção **e** na pasta |
| `faltando` | Está na coleção, **não** está na pasta |
| `extras` | Está na pasta, **não** está mais na coleção |

`extras` é o que revela cópia órfã — o arquivo saiu da coleção mas ficou no
disco. Em modo `manual` isso é esperado; em `auto`, indica falha de remoção.

A comparação usa o nome **sanitizado**, o mesmo que a cópia recebe no destino.
Comparar com o nome cru marcaria como "faltando" todo arquivo cujo nome tenha
caractere inválido no Windows.

#### `DELETE /api/collections/<id>/sync`

Apaga das pastas espelho as cópias dos arquivos informados. É o caminho inverso
do `POST` — espelhar vale nos dois sentidos.

```json
{ "nomes": ["a.jpg", "b.jpg"] }
```

→ `{"status": "ok", "apagados": 2, "falhas": [], "pastas": ["D:\\Fotos\\…"]}`
· `400` sem `nomes` · `404`

Três travas:

| Trava | Efeito |
|---|---|
| Só dentro das pastas registradas | O nome é reduzido a `basename` e sanitizado; `..\..\algo` não escapa |
| Só a cópia | O original nas pastas monitoradas nunca é tocado |
| Nunca apaga diretório | Nome que casar com subpasta é ignorado |

Não exige `confirmar` como a exclusão de pastas: quem chama já confirmou ao
remover da coleção, e o que se apaga é uma cópia gerada pelo próprio app — não
um arquivo do usuário.

#### `POST /api/collections/<id>/sync`

Copia arquivos da coleção para a pasta **já vinculada**. Difere de `/export`:
escreve dentro da pasta existente (não cria `Nome (1)`) e aceita `file_ids`
para copiar só o que acabou de entrar.

```json
{ "file_ids": [42, 43] }
```

Sem `file_ids`, sincroniza a coleção inteira.

→ `{"status": "ok", "copiados": 4, "ja_existiam": 0, "falhas": [], "pastas": ["D:\\…", "E:\\…"], "pasta": "D:\\…"}`
· `400` nenhuma pasta recebendo · `404` · `409` todas as pastas sumiram do disco

Copia para **todas** as pastas do conjunto: `copiados` conta uma cópia por
pasta, então 2 arquivos em 2 pastas dão 4. Se uma pasta sumiu do disco mas
outra continua lá, a cópia acontece nas que sobraram — só falha com 409 quando
nenhuma resta. Falha do arquivo (ausente, fora das pastas monitoradas) é
contada **uma vez**, não uma por destino.

Arquivo que já existe no destino é contado em `ja_existiam` e **não** é
duplicado com sufixo — aqui a intenção é espelhar a coleção, não acumular
versões. `falhas` segue o mesmo formato de `/export`.

#### `POST` / `DELETE /api/collections/<id>/files`
```json
{ "file_id": 42 }
```
→ `{"status": "ok", "acao": "adicionado"}` ou `"removido"`

O `DELETE` devolve também `nomes_removidos`, `modo_sync` e
`pastas_que_recebem`. Os nomes vão na resposta porque, depois do `DELETE`, não
há mais como o frontend saber que arquivo era — e é pelo nome que a cópia é
localizada na pasta espelho.

Adicionar duas vezes é idempotente (não duplica, não dá erro).

Aceita também **lote**, com `file_ids` no lugar de `file_id`:

```json
{ "file_ids": [42, 43, 44] }
```

→ `{"status": "ok", "acao": "adicionado", "adicionados": 2, "ja_existiam": 1,
"ids_adicionados": [43, 44], "pasta_vinculada": null, "modo_sync": "manual"}`

`pasta_vinculada` e `modo_sync` vêm na resposta para o frontend decidir se
deve sincronizar sem precisar de um `GET` extra. `ids_adicionados` traz só o
que realmente entrou — é o que se manda para `/sync`.

No `DELETE` em lote a resposta traz `"removidos": N`. O formato singular
continua válido — as duas chaves são aceitas.

#### `POST /api/collections/<id>/export`

Copia os arquivos da coleção para uma **pasta local**, criando dentro do
destino uma subpasta com o nome da coleção. O `destino` deve vir de
[`GET /api/choose_folder`](#pastas-monitoradas) — não digite caminho à mão.

```json
{ "destino": "D:\\Fotos", "sufixo": "backup", "vincular": false }
```

→ `{"status": "ok", "job_id": "a1b2…", "total": 12, "pasta": "D:\\Fotos\\Natureza_backup"}`

| Campo | Obrigatório | Efeito |
|---|---|---|
| `destino` | sim | Pasta-mãe. Deve vir do seletor nativo |
| `sufixo` | não | Complemento do nome. Sem ele, a numeração é automática |
| `vincular` | não | Qual pasta passa a receber as novas fotos |

**Nomeação.** O nome da coleção é **sempre** o prefixo — é o que permite
reconhecer no Explorer de onde a pasta veio, e ao sistema relacionar as duas:

```
Natureza          1ª exportação
Natureza_2        2ª, sem sufixo
Natureza_backup   sufixo escolhido pelo usuário
Natureza_backup_2 sufixo já em uso
```

**`vincular`** decide o destino das próximas fotos da coleção:

| Valor | Comportamento |
|---|---|
| ausente | Vincula só se ainda não houver pasta vinculada |
| `true` | Passa a apontar para a pasta recém-criada |
| `false` | Mantém o vínculo atual |

Numa re-exportação o frontend manda `false` e pergunta depois qual pasta deve
receber — assumir a mais recente trocaria o destino sem o usuário pedir.

A cópia roda em segundo plano: a resposta volta na hora e o progresso é lido
pelo endpoint de status. Erros **fatais** (nada é copiado) vêm aqui:

- `400` coleção vazia, destino ausente ou pasta inexistente
- `403` sem permissão de escrita no destino
- `404` coleção não encontrada
- `409` já existe uma exportação em andamento para essa coleção

Nunca sobrescreve: se a pasta já existir, cria `Nome (1)`; se um arquivo
colidir, salva como `foto_1.jpg`.

#### `GET /api/collections/export/<job_id>`

```json
{
  "estado": "executando",
  "copiados": 8,
  "total": 12,
  "falhas": [{ "nome": "praia.jpg", "motivo": "nao_encontrado" }],
  "pasta": "D:\\Fotos\\Natureza",
  "colecao": "Natureza",
  "erro": null
}
```

`estado`: `executando` · `concluido` · `cancelado` · `erro`.
Consulte a cada 300–500 ms e **pare o polling** ao sair de `executando`.

Falha em um arquivo não interrompe a exportação — o item entra em `falhas` com
o motivo (`nao_encontrado`, `sem_permissao`, `fora_das_pastas`,
`erro_leitura`) e a cópia segue. `erro` só é preenchido em falha fatal, como
`disco_cheio`.

#### `POST /api/collections/export/<job_id>/cancel`

→ `{"status": "ok", "copiados": 5}`

Cancelamento cooperativo: para entre um arquivo e outro. Os já copiados
**permanecem** no destino — não há rollback de cópia.

#### `GET /api/open_folder?path=<caminho>`

Abre no Explorer uma pasta criada por exportação. Só aceita caminho que conste
numa exportação do próprio usuário — `403` caso contrário. Windows apenas
(`501` em outros sistemas).

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

#### `GET /api/open_location?path=<caminho>`

Abre o Explorer do Windows com o arquivo selecionado. Roda **no servidor**.

→ `{"status": "ok"}` · `400` caminho vazio · `403` fora das pastas monitoradas
· `404` não existe · `501` fora do Windows

Só abre arquivo dentro de uma **pasta monitorada do usuário** — a mesma regra
de `GET /api/file`. A validação resolve links (`realpath`) antes de comparar:
um atalho dentro da pasta monitorada apontando para fora passaria por uma
comparação puramente textual, porque o caminho *escrito* continua dentro.

> Não confundir com [`GET /api/open_folder`](#pastas-monitoradas), que abre uma
> **pasta** e valida contra as pastas **geradas** pelo app (`collection_folders`).
> São listas de autorização diferentes de propósito: uma cobre o acervo
> indexado, a outra o que a exportação criou. Unificá-las daria a cada rota
> permissão que ela não deveria ter.

#### `GET /api/choose_folder` · `GET /api/choose_image`

O seletor de pastas abre no **último diretório usado para exportar**, guardado
em `ultima_pasta_exportacao` dentro do `config_json` do usuário. Se essa pasta
não existir mais, o diálogo abre no padrão do sistema — sem erro. O contrato da
resposta não muda.

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
