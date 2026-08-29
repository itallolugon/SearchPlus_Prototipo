# Feature — Pasta vinculada à coleção

**Data:** 29/08/2026
**Branch:** `feature/selecionar-todas-e-exportacao-imediata`
**Requisitos:** RF-080 … RF-121 · CA-032 … CA-047 ·
[`../09-requisitos-funcionais.md`](../09-requisitos-funcionais.md)
**Status:** implementado.

Substitui o comportamento de "oferta de exportação a cada adição" descrito em
[`13-selecao-em-massa.md`](13-selecao-em-massa.md) §4.

---

## 1. Problema

A exportação imediata resolveu o problema certo pelo meio errado.

Ela eliminava a navegação até Coleções — mas ao custo de **perguntar a cada
adição**. Quem monta uma coleção aos poucos, que é o uso normal, respondia à
mesma pergunta dezenas de vezes numa sessão. E a pergunta chegava sempre no
pior momento: logo depois de adicionar, quando a pessoa quer voltar a pesquisar.

O erro de design foi tratar como **evento** algo que é **preferência**. "Quero
que esta coleção viva também numa pasta" é uma decisão sobre a coleção, tomada
uma vez. Não é uma decisão sobre cada foto.

```
ANTES                              DEPOIS
─────                              ──────
adiciona 3 fotos                   cria a coleção
  → "quer exportar?"                 → "quer uma pasta?" (uma vez)
adiciona 2 fotos                   adiciona 3 fotos  → vão sozinhas
  → "quer exportar?"               adiciona 2 fotos  → vão sozinhas
adiciona 1 foto                    adiciona 1 foto   → vai sozinha
  → "quer exportar?"
```

---

## 2. Conceito: a coleção ganha um espelho

Uma coleção passa a poder ter uma **pasta vinculada** — um diretório no
computador que reflete seu conteúdo.

| | Coleção | Pasta vinculada |
|---|---|---|
| Onde vive | Postgres (`collection_files`) | Disco do usuário |
| O que guarda | Referências a `files.id` | Cópias dos arquivos |
| Existe sem a outra | Sim | Sim (é só uma pasta) |

O vínculo é **opcional** e **por coleção**. Uma coleção sem pasta se comporta
exatamente como antes desta feature.

### Os três modos

Escolhidos uma vez, na criação, e alteráveis depois:

| Modo | O que acontece ao adicionar imagens |
|---|---|
| `auto` | Copia para a pasta na hora, sem perguntar |
| `perguntar` | Confirma a cada adição — para quem quer manter o controle |
| `manual` | Nada automático; a exportação continua no botão (**padrão**) |

`manual` é o padrão e é também o destino de todo caminho de desistência: fechar
o modal, cancelar o seletor de pastas ou dar erro ao criar a pasta deixam a
coleção em `manual`. Nunca se fica num estado meio configurado.

---

## 3. O momento da pergunta

**Uma vez, ao criar a coleção.** É o único momento em que o app pergunta sobre
pasta espontaneamente.

A escolha é boa aqui porque criar uma coleção já é um ato de intenção — a
pessoa está decidindo *"isto vai ser uma coisa"*. Perguntar se essa coisa
também mora no disco é natural nesse instante, e intrusivo em qualquer outro.

Os dois caminhos de criação passam pelo mesmo ponto:

```
criarColecao()            → configurarPastaDaColecao()
criarColecaoEAdicionar()  → adicionarAColecao() → configurarPastaDaColecao()
```

No segundo, a pergunta vem **depois** de adicionar: assim a coleção já está
povoada e o vínculo copia tudo de uma vez.

### O modal

```
┌──────────────────────────────────────────────────┐
│ Enviar esta coleção para uma pasta?              │
│                                                  │
│ A coleção "Arquitetura" pode ter uma pasta no    │
│ seu computador. As imagens que você adicionar a  │
│ ela são copiadas para lá — os originais          │
│ continuam onde estão.                            │
│                                                  │
│   ┌────┐                          ┌──────┐       │
│   │    │  ● ● ●  ──────────▶      │      │       │
│   └────┘                          └──────┘       │
│   Coleção                          Pasta         │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │ Sim — enviar sempre, sem perguntar         │  │
│  ├────────────────────────────────────────────┤  │
│  │ Sim — mas perguntar antes de cada envio    │  │
│  ├────────────────────────────────────────────┤  │
│  │ Não — eu exporto quando quiser             │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

A ilustração é SVG animado: três pontos saem da caixa "Coleção", percorrem a
trilha e desaparecem ao entrar na "Pasta", em cascata. Mostra o que a frase
descreve, para quem não vai ler a frase.

Detalhes que importam:

- **`aria-hidden="true"`** — é decorativa; o texto acima já diz tudo. Anunciar
  um desenho a leitor de tela seria ruído.
- **`prefers-reduced-motion`** — com a preferência ativa, os pontos viram três
  marcas fixas na trilha. A ideia se mantém sem movimento.
- Cada opção é um `<button type="button">` com título e descrição, não um
  `<div>` clicável.

---

## 4. Como funciona por dentro

### 4.1 Modelo de dados

Duas colunas em `collections`, adicionadas via `ALTER TABLE ... IF NOT EXISTS`
no `schema.sql` — que roda a cada boot e é idempotente. Nenhuma migração
manual.

```sql
ALTER TABLE collections ADD COLUMN IF NOT EXISTS pasta_vinculada TEXT;
ALTER TABLE collections ADD COLUMN IF NOT EXISTS modo_sync TEXT NOT NULL DEFAULT 'manual';
```

`DEFAULT 'manual'` faz toda coleção existente continuar se comportando como
antes, sem intervenção.

### 4.2 Endpoints

| Rota | Papel |
|---|---|
| `PATCH /api/collections/<id>` | Renomeia, vincula pasta e define o modo. **Parcial**: só toca os campos presentes no corpo. |
| `POST /api/collections/<id>/sync` | Copia para a pasta já vinculada. Aceita `file_ids` para copiar só o que entrou. |

O `PATCH` aceita `criar_pasta_em` (pasta-mãe): o backend sanitiza o nome da
coleção, cria a subpasta e grava o vínculo — tudo numa chamada. Reaproveita
`_sanitizar_nome()` e `_pasta_disponivel()` da exportação, então a lógica de
nome inválido e colisão é uma só.

Como efeito colateral, o `PATCH` também resolve a lacuna de **renomear
coleção**, que não existia em nenhum endpoint (não havia `PUT` nem `PATCH` no
`app.py` inteiro).

### 4.3 Sincronia ≠ exportação

São operações parecidas com regras opostas num ponto decisivo:

| | Exportação (`/export`) | Sincronia (`/sync`) |
|---|---|---|
| Pasta de destino | Cria nova; se existir, `Nome (1)` | Escreve na pasta vinculada |
| Arquivo homônimo | Nunca sobrescreve: `foto_1.jpg` | **Pula** — conta em `ja_existiam` |
| Escopo | Coleção inteira | Só os `file_ids` recebidos |
| Execução | Job em thread + progresso | Síncrona (poucos arquivos) |

A diferença do arquivo homônimo é o coração da feature. Exportar é tirar uma
foto do estado atual — duas exportações são dois retratos, e nenhum apaga o
outro. Sincronizar é manter um espelho — se `a.jpg` já está lá, criar `a_1.jpg`
faria a pasta divergir da coleção a cada adição.

### 4.4 Só o que é novo

`POST /files` passou a devolver `ids_adicionados` — apenas o que o
`ON CONFLICT DO NOTHING` de fato inseriu. É o que vai para `/sync`.

Sem isso, adicionar 1 imagem a uma coleção de 300 recopiaria as 300 (RF-091).

A mesma resposta traz `pasta_vinculada` e `modo_sync`, para o frontend decidir
o que fazer **sem uma requisição extra a cada adição**.

---

## 5. Decisões

### 5.1 A pasta nunca se desvincula sozinha

Se a pasta sumiu do disco, `/sync` devolve **409** com uma frase que orienta —
e o vínculo permanece. Desvincular automaticamente seria destruir configuração
por causa de algo temporário: um HD externo desconectado, uma pasta de rede
fora do ar. O usuário decide se aponta para outro lugar.

### 5.2 Falha na sincronia não desfaz a adição

Adicionar à coleção e copiar para a pasta são operações independentes
(RF-093). A adição já foi confirmada pelo banco quando a sincronia começa; um
erro de disco não pode reverter um vínculo que o usuário pediu.

### 5.3 Sem barra de progresso na sincronia

A exportação tem job em background e barra de progresso porque copia a coleção
inteira. A sincronia copia o que acabou de ser adicionado — tipicamente de 1 a
20 arquivos. Uma barra apareceria e sumiria antes de ser lida. O resultado vai
num *toast*.

### 5.4 Acesso tolerante às colunas novas

`init_db()` **registra** falhas de DDL em vez de abortar. Se o `ALTER TABLE`
falhar, o app sobe sem as colunas — e uma leitura direta derrubaria **toda**
adição a coleção com HTTP 500.

O código lê o vínculo via `dict(...).get(...)`, então uma migração falha
desativa a sincronia em vez de quebrar o recurso inteiro.

---

## 6. Testes

### Unitários — 26 novos (`tests/unit/test_pasta_vinculada.py`)

| Área | Cobre |
|---|---|
| `PATCH` | Renomear, os três modos, corpo vazio, modo inválido, 401/404, desvincular |
| Parcialidade | Mandar só `modo_sync` **não** apaga a pasta — inspeciona o SQL gerado |
| Criar pasta | Nome sanitizado, colisão vira `Nome (1)`, pasta preexistente intocada |
| Sincronia | Cópia real em disco, originais intactos, homônimo pulado, ausente vira falha, `fora_das_pastas`, pasta sumida → 409 |

Os testes de sincronia tocam o disco de verdade (`tmp_path`): o valor está no
efeito colateral.

### Carga — 1 tarefa nova

`colecao_com_pasta_vinculada` no `locustfile.py`: cria a coleção, vincula a
pasta, adiciona em lote e sincroniza. Mede o par `POST /files` + `POST /sync`,
que no modo `auto` passa a ser a dupla mais frequente do produto.

### Resultado

| | |
|---|---|
| Suíte | **395 passando**, 8 pulados |
| Carga (smoke) | **373 requisições, 0 falhas**, todos os limites respeitados |
| Paridade `app.py` / `mock_server.py` / `API.md` | ✅ |

### Um bug encontrado pelos testes

`/sync` usava `shutil.copy2` mas `shutil` só estava importado **dentro** de
`_worker_exportacao`. A primeira sincronia real teria estourado `NameError`.
O import subiu para o topo do módulo.

---

## 7. Arquivos alterados

| Arquivo | Mudança |
|---|---|
| `backend/schema.sql` | Duas colunas em `collections` |
| `backend/app.py` | `PATCH` da coleção, `POST /sync`, `shutil` no topo, vínculo nas respostas |
| `backend/mock_server.py` | `PATCH` e `/sync` simulados — sem tocar disco |
| `docs/API.md` | Contrato das duas rotas |
| `index.html` | Modal de vínculo com a ilustração SVG |
| `script.js` | `configurarPastaDaColecao()`, `sincronizarSePreciso()`, `enviarParaPastaVinculada()`; remove `oferecerExportacaoImediata()` |
| `style.css` | Modal, animação, selo no card |
| `tests/unit/test_pasta_vinculada.py` | Novo — 26 testes |
| `tests/unit/test_endpoints_dados.py` | Mocks com as colunas novas |
| `tests/load/locustfile.py` | Tarefa do fluxo vinculado |

---

## 7-A. Pastas geradas, abrir e excluir

Adicionado depois, ao aparecer um caso concreto: uma coleção exportada, uma
imagem adicionada em seguida — e a imagem não apareceu na pasta.

### O bug

`/export` criava a pasta e **não guardava o caminho em lugar nenhum**. A
exportação era um retrato sem memória: as imagens adicionadas depois não
tinham destino, e o usuário só descobria ao abrir a pasta e não achar as novas.

**Correção:** exportar agora registra a pasta e passa a apontar para ela. Uma
coleção sem vínculo prévio assume `perguntar`; uma já configurada mantém o
modo que o usuário escolheu.

### Tabela `collection_folders`

Uma coleção pode ter **várias** pastas: exportar duas vezes cria `Natureza` e
`Natureza (1)`. `collections.pasta_vinculada` aponta para a que recebe novas
imagens; a tabela guarda o conjunto completo.

Ela sustenta três coisas que antes eram impossíveis:

1. **Abrir a pasta** — o app precisa saber onde ela está.
2. **Autorizar a abertura** — `/api/open_folder` só aceita caminho registrado.
3. **Excluir com escolha** — listar o que existe no disco.

### Abrir pasta exportada

Botão na tela da coleção. Só aparece quando há pasta de fato no disco: um botão
que dá erro ao ser clicado é pior que nenhum botão. Com mais de uma pasta,
abre a que recebe novas imagens e mostra a contagem no rótulo.

### Excluir coleção → escolher o que fazer com as pastas

```
┌────────────────────────────────────────────────────┐
│ Excluir também as pastas?                          │
│                                                    │
│ A coleção "animes03" gerou estas 2 pastas no seu   │
│ computador. Marque o que quiser apagar — o que     │
│ ficar desmarcado permanece no disco.               │
│                                                    │
│  ☐ animes03  [recebe novas]                        │
│     D:\Fotosnimes03                              │
│     3 arquivos                                     │
│  ☑ animes03                                        │
│     E:\Backupnimes03                             │
│     3 arquivos                                     │
│                                                    │
│  [Cancelar]  [Manter as pastas]  [Apagar marcadas] │
└────────────────────────────────────────────────────┘
```

**Duas etapas.** O primeiro acionamento de "Apagar" só mostra o aviso — quantas
pastas, quantos arquivos, e que **não vão para a Lixeira**. O botão vira
"Confirmar exclusão". Só o segundo executa.

**Manter as pastas é opção de primeira classe**, não um cancelamento
disfarçado: excluir a coleção e preservar os arquivos é uso legítimo — foi
justamente o pedido.

### Travas do backend

`DELETE /folders` apaga arquivo sem lixeira. Três travas, todas obrigatórias:

| Trava | Efeito |
|---|---|
| Lista fechada | Só apaga caminho registrado para **esta** coleção e **este** usuário. Caminho arbitrário existente no disco → `nao_autorizada` |
| Escolha explícita | `caminhos` obrigatório; não existe "apagar todas" implícito |
| Confirmação | `confirmar: true` obrigatório, e precisa ser booleano — a string `"true"` é recusada |

Apagar a pasta vinculada desvincula a coleção e a devolve a `manual`, senão a
próxima adição tentaria copiar para um caminho morto.

Excluir pastas e excluir a coleção são **operações separadas**: uma acontece
sem a outra, nos dois sentidos.

### Várias pastas para a mesma coleção

Exportar duas vezes cria duas pastas. Três decisões saem disso, e nenhuma podia
ser tomada pelo sistema.

**Como chamar a nova.** O nome da coleção é sempre o prefixo — é o que faz o
usuário reconhecer a origem no Explorer:

```
Natureza            1ª exportação
Natureza_2          2ª, numeração automática
Natureza_backup     complemento escolhido
Natureza_backup_2   complemento já em uso
```

O padrão anterior era `Natureza (1)`, estilo Windows. Mudou para `_2` a pedido:
lê melhor como "a segunda pasta da Natureza" e não se confunde com cópia do
sistema operacional.

**Qual pasta recebe as fotos.** Uma re-exportação **não** troca o destino
sozinha. Antes, `/export` sempre vinculava a pasta recém-criada — o usuário
exportava para um backup e, sem perceber, as fotos seguintes paravam de ir para
a pasta principal. Agora o backend aceita `vincular`:

| Valor | Comportamento |
|---|---|
| ausente | Vincula só se ainda não houver pasta vinculada |
| `true` | Passa a apontar para a nova |
| `false` | Mantém o destino atual |

O frontend manda `false` na re-exportação e pergunta depois, com a pasta já
criada e todas as opções na tela.

**Qual abrir.** "Abrir pasta exportada" lista todas, com caminho, contagem de
arquivos e selo em quem recebe as fotos. Dá para abrir qualquer uma ou trocar o
destino ali mesmo. Com uma pasta só, abre direto — um modal de item único para
escolher entre uma opção é burocracia.

### O fluxo de exportar de novo

```
[Exportar coleção]  numa coleção que já tem pasta
         │
         ▼
 "Natureza já foi exportada para 3 pastas"
         │
    ┌────┴─────┐
    ▼          ▼
Numerar     Escolher
 (_4)      complemento     →  Natureza_[____]
    └────┬─────┘               prefixo fixo
         ▼
  seletor nativo de pasta
         ▼
     cópia + progresso
         ▼
 "Para qual pasta vão as próximas fotos?"
   ○ Natureza_praia (a que você acabou de criar)
   ○ Natureza (recebe hoje)
   ○ Natureza_2
```

A pergunta do destino vem **depois** do resultado da cópia, não antes: competir
com a barra de progresso na tela faria o usuário decidir no meio de uma
operação em andamento.

---

## 8. Limitações

| # | Limitação | Observação |
|---|---|---|
| **L-1** | A sincronia é **de mão única**: coleção → pasta. Apagar da pasta não remove da coleção, e vice-versa. | Espelhar nos dois sentidos exigiria vigiar o disco — ver a lacuna 2.1 do levantamento de jornada. |
| **L-2** | Remover da coleção não remove da pasta. | Deliberado: a feature é estritamente aditiva. Apagar arquivo do usuário exigiria confirmação e lixeira. |
| **L-3** | Renomear a coleção não renomeia a pasta. | O vínculo é pelo caminho absoluto, não pelo nome. |
| **L-4** | Sem histórico do que foi sincronizado. | O *toast* informa e some. |
| **L-5** | O modo é por coleção, sem padrão global. | Quem quiser `auto` em tudo escolhe a cada criação. Um padrão em `config_json` resolveria. |
