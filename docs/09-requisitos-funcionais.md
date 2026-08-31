# Requisitos Funcionais — Limpar busca e Coleções/Exportação

**Data:** 25/08/2026
**Escopo:** duas funcionalidades novas — (1) botão de limpar o campo de busca;
(2) seleção de imagens, coleções e exportação para uma pasta local.
**Status:** **implementado** (RF-001 … RF-111). Escrito como especificação,
antes do código: as colunas "Novo/Existente" e o tempo verbal refletem o
estado de 25/08/2026, quando o documento foi redigido.

Documentos irmãos:
[`10-requisitos-nao-funcionais.md`](10-requisitos-nao-funcionais.md) ·
[`features/11-limpar-busca.md`](features/11-limpar-busca.md) ·
[`features/12-colecoes-exportacao.md`](features/12-colecoes-exportacao.md)

---

## 0. Base arquitetural (o que já existe)

Estes requisitos foram escritos **depois** de ler o código. O que segue é fato
verificado, não suposição — e limita o que os requisitos podem exigir.

| Pergunta | Resposta verificada | Evidência |
|---|---|---|
| Que tipo de aplicação é? | **Web local**: Flask serve o frontend estático em `http://127.0.0.1:5000`. Não é Electron, não é Tauri, não é SPA com framework nem build step. | `backend/app.py:701`, `script.js:5` |
| O backend roda na máquina do usuário? | **Sim.** É por isso que diálogos nativos (tkinter) e o Explorer funcionam. | `backend/app.py:1313`, `backend/app.py:3037` |
| Como as imagens são obtidas? | São **arquivos locais já no disco**, varridos de pastas monitoradas. `files.caminho` guarda o caminho absoluto. | `_scan_folder()` em `backend/app.py:3064`, `backend/schema.sql` |
| São URLs / blobs / cache? | **Não.** O frontend só as *exibe* via `GET /api/file/<caminho>`, que lê o arquivo do disco e o devolve. | `backend/app.py:1243`, `script.js:152` |
| Já existe conceito de coleção? | **Sim**, completo: tabelas `collections` e `collection_files`, CRUD na API e UI em modal. | `backend/schema.sql`, `backend/app.py:2497-2657`, `script.js:2399-2636` |
| Já existe favorito? | **Sim**: coluna `files.favorito`, `/api/favorites`, `/api/favorites/toggle`, botão no card. | `backend/app.py:2432-2487`, `script.js:1699-1701` |
| Já existe algo parecido com exportação? | **Não.** Existe apenas "Abrir Arquivo Original" e "Abrir Local no Explorer" para *um* arquivo. | `index.html:376-377` |
| Existe seletor nativo de pasta? | **Sim**, `GET /api/choose_folder` (tkinter `askdirectory`). Hoje só é usado para cadastrar pastas monitoradas. | `backend/app.py:1348` |
| Existe servidor mock? | **Sim**, `backend/mock_server.py` — a API inteira com dados fictícios em `:5001`, sem banco, sem IA, sem credenciais. É o ambiente de desenvolvimento do frontend. | `backend/mock_server.py`, `docs/FRONTEND.md` |
| Existe suíte de testes? | **Sim**, `tests/` com unitários, integração, carga e CI. | `docs/TESTING.md`, `pyproject.toml` |
| Existe contrato de API documentado? | **Sim**, `docs/API.md` — payload, resposta e erros de cada endpoint. | `docs/API.md` |

### Regras do repositório que restringem esta especificação

O `AGENTS.md` na raiz estabelece três regras que moldam o que os requisitos
abaixo podem exigir:

1. **"Não altere `backend/`."** `app.py`, `mock_server.py` e `schema.sql` são o
   motor compartilhado com a versão em produção. *"Havendo necessidade real,
   descreva a proposta em vez de aplicá-la."* — é exatamente o que este
   documento faz: os endpoints da seção 4 são **proposta**, não implementação
   autorizada. A decisão de aplicá-los é de quem mantém o backend.
2. **"Mantenha `app.py`, `mock_server.py` e `docs/API.md` em sincronia."**
   Qualquer endpoint novo precisa existir nos três lugares. Não é
   recomendação: `tests/integration/test_paridade_mock.py` **falha** quando uma
   rota existe só de um lado. Ver RF-061 e RF-062.
3. **A camada visual será substituída.** O `docs/FRONTEND.md` declara
   `index.html`, `style.css` e `script.js` como "reescreva à vontade", com o
   backend intacto. Os requisitos de comportamento aqui valem para a interface
   nova tanto quanto para a atual; as referências de linha ao código de
   frontend servem para descrever o comportamento vigente, não para prescrever
   onde editar.

### Consequência mais importante

**Exportar uma coleção é copiar arquivos locais, não baixar imagens da
internet.** Os casos "URL inválida", "download falhou" e "internet
indisponível" descritos no pedido original **não se aplicam** a esta
arquitetura. Foram substituídos por falhas que de fato podem ocorrer: arquivo
movido/renomeado desde a indexação, permissão negada, disco cheio e colisão de
nomes. Ver `RF-052` e a seção 8 de
[`features/12-colecoes-exportacao.md`](features/12-colecoes-exportacao.md).

### Convenções deste documento

- `RF-nnn` — requisito funcional. `CA-nnn` — critério de aceite.
- **Novo** = não existe hoje. **Existente** = já implementado, incluído aqui
  porque a feature depende dele. **Alterar** = existe, mas precisa mudar.

---

## 1. Busca — limpar o campo

Componente afetado: `#searchInput` (`index.html:286`) dentro de `.search-box`.

| ID | Requisito | Situação |
|---|---|---|
| **RF-001** | O campo de busca deve exibir um botão de limpar (`×`) sempre que contiver ao menos um caractere. | Novo |
| **RF-002** | Com o campo vazio, o botão deve ficar **oculto** (`display:none`), não apenas desabilitado. Decisão registrada em [`features/11-limpar-busca.md` §5](features/11-limpar-busca.md). | Novo |
| **RF-003** | Ao acionar o botão, o conteúdo do campo deve ser apagado integralmente e de forma síncrona, sem chamada de rede. | Novo |
| **RF-004** | Após limpar, o foco deve permanecer (ou retornar) ao campo de busca, com o cursor pronto para digitar. | Novo |
| **RF-005** | Acionar o botão **não** deve recarregar a página, navegar, nem disparar `realizarBusca()`. | Novo |
| **RF-006** | Limpar o campo **não** deve apagar os resultados já exibidos nem retornar à home. Limpar o texto e sair da tela de resultados são ações distintas — a segunda já existe no clique sobre o logo (`voltarParaHomeSmooth()`, `script.js:1403`). | Novo |
| **RF-007** | O botão deve ser alcançável e acionável por teclado (`Tab` → `Enter`/`Espaço`), sendo um `<button type="button">` real. | Novo |
| **RF-008** | O botão não pode sobrepor, deslocar ou capturar cliques dos controles existentes `📷 Buscar por imagem` (`index.html:287`) e `Buscar` (`index.html:288`). | Novo |
| **RF-009** | O comportamento deve ser idêntico em desktop e nos dois *breakpoints* já definidos no projeto (`style.css:1042` e `style.css:1077`), inclusive quando a `.search-box` passa a `flex-direction: column`. | Novo |
| **RF-010** | A visibilidade do botão deve refletir o valor real do campo em **todos** os pontos que o alteram por código: `usarHistorico()` (`script.js:1334`), `voltarParaHomeSmooth()` (`script.js:1403`) e `limparBusca()` (`script.js:2050`). | Alterar |
| **RF-011** | Clicar no botão não pode fechar o dropdown de histórico antes que o clique seja processado. O `onblur` do input agenda `esconderHistorico()` (`index.html:286`); o botão deve neutralizar essa corrida. | Novo |
| **RF-012** | O botão deve possuir `aria-label` e `title`, seguindo o padrão já usado em `#btnMenu` (`index.html:247`), único elemento do projeto com `aria-label` hoje. | Novo |

> **Fora de escopo desta especificação:** limpar o campo com a tecla `Escape`.
> O projeto já usa `Escape` como "fechar a janela aberta mais relevante"
> (`script.js:2358`) e sobrecarregar a tecla exigiria decisão de produto. Ver
> "Decisões pendentes" no final (`D-1`).

---

## 2. Seleção de imagens

Hoje só é possível vincular **um** arquivo por vez a uma coleção, e apenas com
o painel lateral aberto — `abrirSeletorColecao()` depende da variável global
`_fileIdAtual`, preenchida em `abrirPainelLateral()` (`script.js:1765`). Não
existe seleção múltipla.

| ID | Requisito | Situação |
|---|---|---|
| **RF-013** | Cada card de resultado deve oferecer um controle de **seleção** (caixa `☑`) independente do controle de **favorito** (`♥`). | Novo |
| **RF-014** | Selecionar e favoritar são ações semanticamente distintas e **não** podem se afetar: selecionar não favorita, desfavoritar não remove da seleção. | Novo |
| **RF-015** | O controle de favorito existente (`.btn-fav-abs`, `script.js:1701`) deve permanecer com aparência, posição e comportamento inalterados. | Existente |
| **RF-016** | Um card selecionado deve ter estado visual persistente (não só no *hover*), distinguível do card favoritado. | Novo |
| **RF-017** | Enquanto houver ao menos um item selecionado, uma barra de ações deve exibir a contagem e oferecer, no mínimo: *Adicionar à coleção* e *Limpar seleção*. | Novo |
| **RF-018** | A seleção é **efêmera e de sessão de navegação**: vive em memória no frontend, não é persistida no banco, e é descartada ao recarregar a página ou fazer logout. | Novo |
| **RF-019** | A seleção deve sobreviver à troca de filtro (`filtroAtual`) e à re-renderização de `renderizarResultados()` (`script.js:1666`), que hoje reconstrói o grid inteiro via `innerHTML`. | Novo |
| **RF-020** | Uma nova busca deve limpar a seleção, para não misturar itens de contextos diferentes sem que o usuário perceba. | Novo |
| **RF-021** | A identidade de uma imagem, para qualquer fim (seleção, coleção, exportação), é a chave primária `files.id`. Nome de arquivo e caminho **não** são identificadores. | Existente |

---

## 3. Coleções

| ID | Requisito | Situação |
|---|---|---|
| **RF-022** | O usuário deve poder criar uma coleção informando um nome. | Existente — `POST /api/collections` (`backend/app.py:2497`), `criarColecao()` (`script.js:2471`) |
| **RF-023** | O nome da coleção deve ser único por usuário; a tentativa de repetir deve retornar erro compreensível, não erro técnico. | Existente — `UNIQUE (user_id, nome)` + tratamento de `UniqueViolation` → HTTP 409 |
| **RF-024** | O nome da coleção deve ser rejeitado se vazio ou apenas espaços. | Existente |
| **RF-025** | O usuário deve poder adicionar **uma** imagem aberta a uma coleção. | Existente — `abrirSeletorColecao()` / `adicionarAColecao()` (`script.js:2573-2636`) |
| **RF-026** | O usuário deve poder adicionar **todas as imagens selecionadas** (RF-013) a uma coleção numa única ação. | Novo |
| **RF-027** | A mesma imagem não pode constar duas vezes na mesma coleção. Re-adicionar é **idempotente**: não gera erro, não duplica. | Existente — PK composta `(collection_id, file_id)` + `ON CONFLICT DO NOTHING` (`backend/app.py:2645`) |
| **RF-028** | Ao adicionar em lote, o sistema deve informar quantos itens foram efetivamente adicionados e quantos já estavam na coleção. | Novo — o endpoint atual não distingue inserido de ignorado |
| **RF-029** | O usuário deve poder remover uma imagem da coleção. Remover da coleção **não** apaga o arquivo do disco nem o desfavorita. | Existente — `DELETE /api/collections/<id>/files` (`backend/app.py:2609`), `removerDaColecao()` (`script.js:2555`) |
| **RF-030** | O usuário deve poder visualizar o conteúdo de uma coleção e a contagem de itens. | Existente — `verColecao()` (`script.js:2502`) |
| **RF-031** | O usuário deve poder excluir uma coleção. Os arquivos não são apagados — só o agrupamento. | Existente — `excluirColecao()` (`script.js:2491`); o `ON DELETE CASCADE` atinge apenas `collection_files` |
| **RF-032** | Toda operação de coleção deve validar que a coleção **e** o arquivo pertencem ao usuário autenticado. | Existente — verificação dupla de posse em `backend/app.py:2621-2630` |

---

## 4. Exportação para pasta local

Nada nesta seção existia quando o documento foi escrito — toda a exportação
é trabalho novo, hoje implementado.

### 4.1 Disparo e destino

| ID | Requisito |
|---|---|
| **RF-033** | A tela de uma coleção aberta deve oferecer a ação **"Exportar coleção"**, ao lado de "← Voltar às coleções" (`index.html:829`). Justificativa do rótulo em [`features/12-colecoes-exportacao.md` §7](features/12-colecoes-exportacao.md). |
| **RF-034** | A ação deve ser bloqueada, com mensagem explicativa, quando a coleção estiver vazia. Nenhum diálogo de pasta deve abrir nesse caso. |
| **RF-035** | O usuário deve escolher a **pasta de destino** por meio do seletor nativo já existente (`GET /api/choose_folder`, `backend/app.py:1348`). Nenhum caminho pode ser digitado à mão pelo usuário na primeira versão. |
| **RF-036** | Cancelar o seletor de pasta deve abortar a exportação silenciosamente, sem erro. O endpoint já retorna `{"status": "cancelado"}`. |
| **RF-037** | Dentro da pasta escolhida, o sistema deve criar uma **subpasta** com o nome da coleção. Os arquivos nunca são despejados soltos no destino escolhido. |

### 4.2 Nomes

| ID | Requisito |
|---|---|
| **RF-038** | O nome da subpasta deve ser derivado do nome da coleção após **sanitização**: remoção dos caracteres proibidos pelo Windows (`< > : " / \ \| ? *` e controles `0x00–0x1F`), corte de pontos e espaços finais, e substituição de nomes reservados (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`). |
| **RF-039** | Se a sanitização resultar em nome vazio, deve ser usado um substituto determinístico — `colecao_<id>`. |
| **RF-040** | O caminho completo de cada arquivo de destino deve respeitar o limite de 260 caracteres do Windows. O nome-base deve ser truncado, preservando a extensão, quando necessário. |
| **RF-041** | Se já existir uma pasta com o nome sanitizado no destino, o sistema deve criar `Nome (1)`, `Nome (2)`, … . Uma exportação **nunca** escreve dentro de uma pasta preexistente. |
| **RF-042** | Colisão de nome de arquivo dentro da pasta exportada deve ser resolvida com sufixo incremental: `foto.jpg`, `foto_1.jpg`, `foto_2.jpg`. Colisão é esperada — dois arquivos de pastas monitoradas diferentes podem se chamar `IMG_0001.jpg`. |
| **RF-043** | Nenhum arquivo existente pode ser sobrescrito em nenhuma circunstância. |

### 4.3 Cópia

| ID | Requisito |
|---|---|
| **RF-044** | Os arquivos devem ser **copiados**, jamais movidos ou removidos da origem. A coleção permanece intacta após a exportação. |
| **RF-045** | Cada caminho de origem deve ser validado antes da leitura, com a mesma regra anti-*path traversal* já aplicada em `GET /api/file` (`backend/app.py:1263-1278`): o arquivo precisa estar dentro de uma pasta monitorada do usuário. |
| **RF-046** | A exportação deve preservar os *timestamps* originais dos arquivos (equivalente a `shutil.copy2`). |
| **RF-047** | Duas entradas distintas da coleção (`files.id` diferentes) que apontem para arquivos idênticos em conteúdo devem ser **ambas** exportadas, com nomes resolvidos por RF-042. Deduplicação por conteúdo não faz parte desta versão — ver `D-4`. |

### 4.4 Progresso, conclusão e erros

| ID | Requisito |
|---|---|
| **RF-048** | A exportação deve rodar de forma **assíncrona** no backend, sem bloquear a interface nem a requisição HTTP que a iniciou. |
| **RF-049** | A interface deve exibir progresso durante a operação, no mínimo como `N de M imagens` com barra proporcional. |
| **RF-050** | Deve existir consulta de estado da exportação em andamento, seguindo o padrão de *polling* já usado pela barra de status (`buscarStatus()` a cada 2 s, `script.js:2323`) — porém com intervalo mais curto, adequado a uma operação interativa. |
| **RF-051** | Ao concluir, a interface deve exibir um resumo: total copiado, total falho e o caminho da pasta criada. |
| **RF-052** | Falha em um arquivo individual **não** aborta a exportação. O item é registrado como falho, com motivo, e a operação segue para o próximo. |
| **RF-053** | Ao final de uma exportação parcial, o usuário deve poder ver **quais** arquivos falharam e por quê. Um número solto ("2 falharam") não satisfaz este requisito. |
| **RF-054** | Erros **fatais** — impossível criar a pasta de destino, permissão negada no destino, disco cheio — devem abortar a exportação, informar a causa em linguagem comum e preservar o que já foi copiado, sem apagar nada. |
| **RF-055** | Nenhuma mensagem de erro exibida ao usuário pode ser um *traceback*, um código de exceção do Python ou um caminho interno do servidor. O detalhe técnico vai para o log do backend. |
| **RF-056** | O usuário deve poder **cancelar** uma exportação em andamento. Os arquivos já copiados permanecem no destino e o usuário é informado disso. |
| **RF-057** | Não pode haver duas exportações simultâneas da mesma coleção pelo mesmo usuário. A segunda tentativa deve ser recusada com mensagem clara. |
| **RF-058** | Concluída a exportação, deve ser oferecida a ação **"Abrir pasta"**, que abre a pasta criada no Explorer. |
| **RF-059** | O endpoint que abre a pasta deve validar que o caminho corresponde a uma exportação real feita naquela sessão. Observação: o `/api/open_location` atual (`backend/app.py:3037`) **não faz nenhuma validação de caminho** — ver o risco `R-03` em [`features/12-colecoes-exportacao.md`](features/12-colecoes-exportacao.md). |
| **RF-060** | "Abrir pasta" é dependente de Windows. Em qualquer outra plataforma, a ação deve ser omitida e o caminho exibido como texto copiável — nunca um botão que falha em silêncio. |

### 4.5 Paridade do repositório

Requisitos impostos pelo `AGENTS.md` e verificados automaticamente pela suíte
de testes. Valem para **todo** endpoint novo proposto na seção 4.

| ID | Requisito |
|---|---|
| **RF-061** | Todo endpoint novo deve ser implementado também em `backend/mock_server.py`, com dados fictícios e o **mesmo formato de resposta** do backend real. `tests/integration/test_paridade_mock.py` compara os dois `url_map` e falha se uma rota existir só de um lado. |
| **RF-062** | Todo endpoint novo deve ser documentado em `docs/API.md`, na seção "Coleções", seguindo o formato já usado ali: bloco JSON do corpo, seta `→` com a resposta de sucesso e a lista de códigos de erro. O mesmo teste de paridade confere o `API.md`. |
| **RF-063** | O mock deve simular a exportação de forma **inócua**: progresso e resumo realistas, sem criar pastas nem copiar arquivos no disco de quem desenvolve o frontend. Um mock que escreve em disco é uma armadilha. |
| **RF-064** | O mock deve permitir exercitar os caminhos de erro (exportação parcial, permissão negada, cancelamento), não apenas o caminho feliz — do contrário RF-052 a RF-056 ficam sem como ser desenvolvidos contra o mock. |

---

## 4-A. Seleção em massa e exportação imediata

Evolução de fluxo sobre o que as seções 2 a 4 já definem. Detalhes de
implementação em [`features/13-selecao-em-massa.md`](features/13-selecao-em-massa.md).

### Selecionar tudo

| ID | Requisito | Situação |
|---|---|---|
| **RF-065** | A tela de resultados deve oferecer uma ação para selecionar de uma vez **todas as imagens elegíveis atualmente exibidas**. | Implementado |
| **RF-066** | "Tudo" é o conjunto dos resultados da busca atual que passam pelo filtro ativo — **não** o acervo inteiro. O `/api/search` devolve a lista completa numa resposta só (sem paginação, sem *scroll* infinito, sem virtualização), então "carregado" e "exibido" coincidem. | Implementado |
| **RF-067** | O mesmo controle deve desfazer a seleção em massa quando tudo já estiver selecionado, alternando o rótulo entre *Selecionar tudo* e *Desmarcar tudo*. | Implementado |
| **RF-068** | Com seleção parcial, o controle deve exibir *Selecionar tudo* e, ao ser acionado, **completar** a seleção em vez de invertê-la. | Implementado |
| **RF-069** | A interface deve exibir a contagem de resultados e, havendo seleção, quantos estão marcados. | Implementado |
| **RF-070** | A seleção em massa e a individual compartilham o mesmo estado: desmarcar um card depois de "selecionar tudo" deve refletir no contador e no rótulo do botão, e remarcá-lo deve devolver o estado anterior. | Implementado |
| **RF-071** | Sem resultados, a barra de ações deve ficar oculta — não há o que selecionar. | Implementado |
| **RF-072** | A elegibilidade de cada item segue a regra de seleção já existente (RF-013). A seleção em massa **não** cria nem relaxa critério próprio. | Implementado |

### Exportação imediata

> **Substituído por RF-080 … RF-092.** A primeira versão perguntava "quer
> exportar?" a **cada** adição. Na prática virou interrupção: quem monta uma
> coleção aos poucos respondia a mesma pergunta dezenas de vezes. Os requisitos
> abaixo ficam registrados como histórico da decisão; o comportamento vigente é
> o da pasta vinculada.

| ID | Requisito | Situação |
|---|---|---|
| **RF-073** | Concluída a adição de imagens a uma coleção, a interface deve oferecer a exportação daquela coleção. | ~~Implementado~~ → substituído por RF-084 |
| **RF-074** | A oferta é **opcional**: recusar mantém o usuário onde estava. | Preservado em RF-086 |
| **RF-075** | A exportação imediata deve reutilizar `exportarColecao()`. É proibido um segundo mecanismo de exportação. | Vigente — vale para toda a feature |
| **RF-076** | A exportação deve usar o estado **atual** da coleção. | Vigente |
| **RF-077** | A confirmação deve informar o total de itens. Falha ao obter o total não bloqueia a oferta. | ~~Implementado~~ → substituído |
| **RF-078** | Recusar, cancelar ou falhar **não** pode desfazer a adição. | Vigente — RF-092 |
| **RF-079** | Coleção vazia não recebe oferta de exportação. | Vigente |

---

## 4-B. Pasta vinculada à coleção

Uma coleção pode ter uma **pasta espelho** no computador. A decisão é tomada
**uma única vez**, na criação da coleção, e vale para todas as adições
seguintes. Detalhes em
[`features/14-pasta-vinculada.md`](features/14-pasta-vinculada.md).

### Vínculo

| ID | Requisito | Situação |
|---|---|---|
| **RF-080** | Uma coleção pode ter, opcionalmente, uma pasta vinculada no computador do usuário, persistida em `collections.pasta_vinculada`. | Implementado |
| **RF-081** | O vínculo deve ser oferecido **uma única vez**, no momento da criação da coleção. O app não pode voltar a perguntar espontaneamente. | Implementado |
| **RF-082** | A oferta deve apresentar três escolhas: enviar sempre sem perguntar (`auto`), perguntar antes de cada envio (`perguntar`), ou não vincular (`manual`). | Implementado |
| **RF-083** | A oferta deve incluir uma ilustração animada do fluxo coleção → pasta, para tornar o conceito compreensível sem leitura. | Implementado |
| **RF-084** | Recusar o vínculo, cancelar o seletor de pastas ou fechar o modal deixa a coleção em `manual` — o comportamento anterior à feature. | Implementado |
| **RF-085** | A pasta vinculada deve ser criada dentro da pasta-mãe escolhida, com o nome sanitizado da coleção, reutilizando a mesma lógica da exportação. | Implementado |
| **RF-086** | O usuário deve poder alterar o modo e a pasta depois, e desvincular. Desvincular devolve a coleção a `manual`. | Implementado |
| **RF-087** | A interface deve mostrar, no card da coleção, que ela tem pasta vinculada e em que modo. | Implementado |

### Sincronia

| ID | Requisito | Situação |
|---|---|---|
| **RF-088** | Em `auto`, imagens adicionadas à coleção são copiadas para a pasta vinculada imediatamente, sem confirmação. | Implementado |
| **RF-089** | Em `perguntar`, cada adição pede confirmação antes de copiar. Recusar não desfaz a adição à coleção. | Implementado |
| **RF-090** | Em `manual`, nada é copiado automaticamente; a exportação continua disponível pelo botão. | Implementado |
| **RF-091** | A sincronia deve copiar **apenas os itens recém-adicionados**, não a coleção inteira. Adicionar 1 imagem a uma coleção de 300 copia 1 arquivo. | Implementado |
| **RF-092** | A sincronia escreve **dentro** da pasta vinculada. Arquivo já presente no destino é contado como existente e **pulado** — não duplicado com sufixo. A pasta é um espelho, não um acumulador de versões. | Implementado |
| **RF-093** | Falha na sincronia não pode desfazer a adição à coleção. As duas operações são independentes. | Implementado |
| **RF-094** | Se a pasta vinculada não existir mais, a sincronia deve falhar com mensagem que oriente a revincular — e **não** desvincular sozinha. | Implementado |
| **RF-095** | A sincronia deve validar a origem com a mesma regra anti-*path traversal* da exportação (RF-045). | Implementado |

### Pastas geradas

| ID | Requisito | Situação |
|---|---|---|
| **RF-096** | Toda pasta criada pelo app para uma coleção deve ser registrada em `collection_folders`, com o caminho absoluto. | Implementado |
| **RF-097** | Exportar uma coleção deve **vincular** a pasta criada, para que imagens adicionadas depois tenham destino. Uma coleção sem vínculo prévio assume `modo_sync: 'perguntar'`; uma já configurada mantém o modo escolhido. | Implementado |
| **RF-098** | A tela da coleção deve oferecer **"Abrir pasta exportada"**, que abre a pasta no Explorer. Havendo mais de uma, abre a que recebe novas imagens. | Implementado |
| **RF-099** | O botão de abrir só aparece quando existe pasta de fato no disco. Um botão que falha ao ser clicado é pior que nenhum botão. | Implementado |
| **RF-100** | `GET /api/open_folder` deve autorizar apenas caminhos registrados para o usuário — nunca um caminho arbitrário. | Implementado |

### Excluir coleção e pastas

| ID | Requisito | Situação |
|---|---|---|
| **RF-101** | Ao excluir uma coleção que gerou pastas, o sistema deve perguntar o que fazer com elas **antes** de excluir. | Implementado |
| **RF-102** | O diálogo deve listar **todas** as pastas existentes, com nome, caminho completo e quantidade de arquivos, e marcar qual recebe novas imagens. | Implementado |
| **RF-103** | A escolha é **por pasta**: o usuário marca o que apagar. Apagar uma e manter outra deve ser possível. | Implementado |
| **RF-104** | Manter as pastas deve ser uma opção de primeira classe — excluir a coleção e preservar os arquivos no disco é uso legítimo. | Implementado |
| **RF-105** | A exclusão de pastas exige **duas etapas**: o primeiro acionamento apresenta o que será apagado; só o segundo executa. | Implementado |
| **RF-106** | O aviso da segunda etapa deve informar quantas pastas e quantos arquivos serão apagados, e que **não vão para a Lixeira**. | Implementado |
| **RF-107** | O backend deve recusar apagar caminho não registrado para aquela coleção e usuário, mesmo que exista no disco. | Implementado |
| **RF-108** | O backend deve exigir `confirmar: true` e uma lista explícita de caminhos. Não existe "apagar todas" implícito. | Implementado |
| **RF-109** | Apagar a pasta vinculada deve desvincular a coleção e devolvê-la a `manual`, para a próxima adição não tentar copiar para um caminho morto. | Implementado |
| **RF-110** | Cancelar o diálogo cancela também a exclusão da coleção. | Implementado |
| **RF-111** | Excluir pastas e excluir a coleção são operações independentes: uma pode acontecer sem a outra. | Implementado |

### Múltiplas pastas por coleção

| ID | Requisito | Situação |
|---|---|---|
| **RF-112** | O nome da coleção deve ser **sempre** o prefixo da pasta gerada. É o que permite reconhecer a origem no Explorer e relacionar pasta e coleção. | Implementado |
| **RF-113** | Exportações seguintes devem numerar a partir de 2 preservando o prefixo — `Natureza`, `Natureza_2`, `Natureza_3`. | Implementado |
| **RF-114** | O usuário deve poder escolher o complemento do nome em vez da numeração: `Natureza_backup`, `Natureza_praia`. O prefixo permanece fixo e não é editável. | Implementado |
| **RF-115** | O complemento escolhido deve ser sanitizado pelas mesmas regras do nome da pasta, e numerado se já estiver em uso (`Natureza_backup_2`). | Implementado |
| **RF-116** | Ao acionar "Exportar" numa coleção já exportada, o sistema deve **avisar** que ela já tem pasta e quantas, antes de criar outra. | Implementado |
| **RF-117** | Uma re-exportação **não** pode mudar sozinha qual pasta recebe as novas fotos. A troca é decisão explícita do usuário. | Implementado |
| **RF-118** | Após criar a nova pasta, o sistema deve perguntar para qual das pastas vão as próximas fotos, listando todas como opção. | Implementado |
| **RF-119** | "Abrir pasta exportada" deve listar **todas** as pastas e deixar o usuário escolher qual abrir. Com uma só, abre direto. | Implementado |
| **RF-120** | A lista deve indicar visualmente qual pasta está recebendo as fotos, e permitir trocar ali mesmo. | Implementado |
| **RF-121** | O usuário deve conseguir saber, a qualquer momento, para qual pasta as fotos da coleção estão indo. | Implementado |

### Conjunto de pastas de destino

| ID | Requisito | Situação |
|---|---|---|
| **RF-122** | O destino das novas imagens é um **conjunto** de pastas, não um valor único. Persistido em `collection_folders.recebe`. | Implementado |
| **RF-123** | O usuário deve poder marcar **várias** pastas para receber ao mesmo tempo, espelhando a coleção em mais de um lugar. | Implementado |
| **RF-124** | O usuário deve poder deixar **nenhuma** pasta marcada. As pastas já criadas permanecem registradas e abríveis; apenas o envio automático para. | Implementado |
| **RF-125** | A sincronia deve copiar cada arquivo uma vez **por pasta** do conjunto. Dois arquivos em duas pastas resultam em quatro cópias. | Implementado |
| **RF-126** | Falha do arquivo (ausente, fora das pastas monitoradas) deve ser contada **uma vez**, não uma por destino — senão o resumo multiplicaria a mesma falha. | Implementado |
| **RF-127** | Se uma pasta do conjunto sumir do disco, a cópia deve prosseguir nas restantes. Só falha quando **nenhuma** resta. | Implementado |
| **RF-128** | A interface deve usar caixas de marcação, e informar quantas e quais pastas estão recebendo. | Implementado |
| **RF-129** | Após uma re-exportação, o usuário deve poder escolher entre atalhos (só a nova, todas, nenhuma) ou marcar exatamente quais. | Implementado |
| **RF-130** | Coleções que usavam destino único devem migrar sem intervenção: a pasta apontada por `pasta_vinculada` vira o primeiro elemento do conjunto. | Implementado |

### Configurações da coleção

| ID | Requisito | Situação |
|---|---|---|
| **RF-131** | A tela da coleção deve oferecer **Configurações**, onde o modo de envio pode ser alterado a qualquer momento. Antes, ele só era escolhido na criação e ficava sem como mudar. | Implementado |
| **RF-132** | A tela deve reapresentar a ilustração animada do fluxo coleção → pasta. Quem a abre meses depois precisa reentender o conceito, não só ver três opções soltas. | Implementado |
| **RF-133** | O modo em vigor deve estar visualmente identificado entre as opções. | Implementado |
| **RF-134** | A tela deve informar o destino atual e, quando não houver pasta ou nenhuma estiver marcada, dizer que o envio automático não tem para onde ir. | Implementado |
| **RF-135** | A lista de pastas deve oferecer marcar/desmarcar **todas** de uma vez. Com uma pasta só, a ação não aparece — não significaria nada além do próprio item. | Implementado |

### Espelho nos dois sentidos

| ID | Requisito | Situação |
|---|---|---|
| **RF-136** | Remover uma imagem da coleção deve remover a **cópia** das pastas que recebem, conforme o modo: `auto` apaga sem perguntar, `perguntar` confirma, `manual` não toca. | Implementado |
| **RF-137** | A remoção só pode apagar a cópia. O arquivo **original** nas pastas monitoradas nunca é tocado. | Implementado |
| **RF-138** | A remoção deve ser confinada às pastas registradas: o nome é reduzido a `basename` e sanitizado, de modo que `..\..lgo` não escape. | Implementado |
| **RF-139** | A remoção nunca pode apagar diretório. Nome que casar com subpasta é ignorado. | Implementado |
| **RF-140** | Falha ao apagar da pasta **não** pode desfazer a remoção da coleção. As duas operações são independentes. | Implementado |
| **RF-141** | As descrições dos modos devem explicar o comportamento nos **dois sentidos** — adição e remoção. Quem escolhe "enviar sempre" precisa saber que remover também apaga, antes de escolher. | Implementado |

### Status da pasta

| ID | Requisito | Situação |
|---|---|---|
| **RF-142** | A tela da coleção deve oferecer **Status da pasta**, mostrando por pasta quais imagens já foram copiadas e quais faltam — em número e em nome. | Implementado |
| **RF-143** | O status deve listar também os **extras**: arquivos na pasta que não estão mais na coleção. Revela cópia órfã. | Implementado |
| **RF-144** | A comparação deve usar o nome **sanitizado**, o mesmo que a cópia recebe no destino. Comparar com o nome cru marcaria como faltando todo arquivo com caractere inválido. | Implementado |
| **RF-145** | O status deve permitir copiar as faltantes direto dali — é o motivo de abrir a tela no modo manual. | Implementado |
| **RF-146** | Cada pasta deve exibir barra de progresso acessível (`role="progressbar"` com `aria-valuenow`/`min`/`max`). | Implementado |

### Estado do favorito

| ID | Requisito | Situação |
|---|---|---|
| **RF-147** | O botão de favorito deve indicar visualmente o estado **favoritado**. Antes ele renderizava conteúdo vazio: um círculo em branco, sem informação nenhuma. | Corrigido |
| **RF-148** | A distinção não pode ser só de cor: o glifo muda de `♡` (vazado) para `♥` (cheio). | Corrigido |
| **RF-149** | Os glifos devem ser caracteres de **texto**, não emoji. O emoji `🤍` traz cor própria e ignora `color`, o que impedia a regra `.is-fav` de pintá-lo. | Corrigido |
| **RF-150** | O botão deve ser `<button type="button">` com `aria-pressed` e `aria-label` que acompanham o estado. | Corrigido |

### Verificar alterações numa pasta

A indexação é um retrato do momento da varredura. Até aqui o Search+ só sabia
somar: arquivo editado nunca era relido (a varredura pula tudo que já está
processado) e arquivo apagado continuava aparecendo na busca para sempre,
levando a um clique que não abre nada.

| ID | Requisito | Situação |
|---|---|---|
| **RF-154** | Cada pasta monitorada deve oferecer **Verificar**, que compara a pasta no disco com o que está indexado. | Implementado |
| **RF-155** | A comparação deve usar **data de modificação e tamanho**. É o par mais barato que distingue arquivo editado de intocado sem precisar abrir o arquivo. | Implementado |
| **RF-156** | Arquivo que está no disco e não no índice é **novo**: entra no índice e vai para a fila de análise. | Implementado |
| **RF-157** | Arquivo cuja assinatura mudou é **alterado**: perde a descrição antiga e é reanalisado. A descrição anterior descrevia um conteúdo que não existe mais. | Implementado |
| **RF-158** | Arquivo que sumiu do disco é **marcado**, nunca apagado. O motivo mais comum de um arquivo sumir é um disco externo desconectado; apagar o registro jogaria fora a descrição da IA, os embeddings e a participação do arquivo em coleções. | Implementado |
| **RF-159** | Arquivo marcado como ausente que reaparece deve ser **desmarcado** sozinho na verificação seguinte. | Implementado |
| **RF-160** | Arquivo já marcado como ausente não pode ser recontado a cada verificação — senão o número nunca zera. | Implementado |
| **RF-161** | A comparação de caminhos deve ignorar caixa. No Windows `C:\Fotos\A.JPG` e `C:\fotos\a.jpg` são o mesmo arquivo; comparar cru o marcaria como ausente **e** novo ao mesmo tempo. | Implementado |
| **RF-162** | Arquivo indexado antes das colunas de assinatura existirem tem assinatura nula. Nulo significa "nunca soube como era", não "mudou": ele ganha a assinatura em silêncio e **não** é reanalisado. Tratar como alteração mandaria a biblioteca inteira para a fila da IA na primeira verificação depois da atualização. | Implementado |
| **RF-163** | A diferença de data deve tolerar **2 segundos**. FAT32 e pendrives guardam a hora com essa resolução, e copiar a mesma foto para lá e de volta desloca a data sem que um byte mude. | Implementado |
| **RF-164** | Se a pasta inteira não puder ser aberta, a verificação deve **avisar e não marcar nada**. Marcar todos os arquivos tiraria a biblioteca inteira da busca por causa de um cabo solto. | Implementado |
| **RF-165** | O resultado deve ser exibido em contagem e nomes: novos, alterados, ausentes e reaparecidos. | Implementado |
| **RF-166** | A verificação deve responder de forma síncrona. Quem clicou está olhando para a tela esperando um número; só a análise de IA corre em segundo plano. | Implementado |
| **RF-167** | A varredura da indexação e a da verificação devem enxergar **o mesmo conjunto de arquivos** (mesmas extensões, mesma lista de pastas ignoradas). Divergir faria a verificação acusar como novo algo que a indexação ignora de propósito, e o contador nunca zeraria. | Implementado |
| **RF-168** | A verificação não pode acontecer por GET. Um link ou um prefetch do navegador dispararia reindexação sozinho. | Implementado |

### Desfazer exclusões

Excluir uma coleção apagava trabalho que não volta: o agrupamento montado à mão
e o vínculo com as pastas geradas no disco. Um clique errado custava tudo isso
sem recurso.

| ID | Requisito | Situação |
|---|---|---|
| **RF-180** | Excluir uma coleção deve guardar um **retrato** do que foi apagado, e oferecer desfazer. | Implementado |
| **RF-181** | Remover imagens de uma coleção deve oferecer o mesmo desfazer. | Implementado |
| **RF-182** | O botão "desfazer" fica **8 segundos** na tela: tempo de ler, entender e alcançar o botão, sem atravancar. | Implementado |
| **RF-183** | Quem perder os 8 segundos deve encontrar o item na **lixeira**, dentro das Configurações. | Implementado |
| **RF-184** | O que está na lixeira é descartado após **30 dias**. O expurgo roda a cada uso da lixeira. | Implementado |
| **RF-185** | A coleção restaurada deve voltar com o **mesmo identificador**. Voltar com outro faria dela uma coleção diferente, e o que apontasse para a antiga passaria a apontar para o nada. | Implementado |
| **RF-186** | A restauração deve devolver também as **pastas geradas** e o modo de envio. | Implementado |
| **RF-187** | Arquivo que o usuário apagou da biblioteca nesse meio-tempo é **pulado**. Falhar a restauração inteira por causa de uma foto seria pior que devolver a coleção sem ela. | Implementado |
| **RF-188** | Se o nome foi reaproveitado por outra coleção, a restauração deve **recusar com explicação** — não com erro de banco. | Implementado |
| **RF-189** | O item só sai da lixeira **depois** que a restauração deu certo. Sair antes deixaria o usuário sem a coleção e sem o que a traria de volta. | Implementado |
| **RF-190** | Descartar da lixeira é definitivo e deve pedir confirmação. É a única exclusão sem desfazer do app, e é assim de propósito: a lixeira **é** o desfazer. | Implementado |
| **RF-191** | O botão "desfazer" se desabilita ao ser clicado. Dois cliques mandariam dois pedidos, e o segundo acharia o item já restaurado e devolveria erro — um erro na tela por ter clicado com vontade. | Implementado |
| **RF-192** | As pastas apagadas do disco **não** voltam com o desfazer. Quem escolheu apagá-las já confirmou em duas etapas, e ressuscitar arquivo apagado não é algo que o app possa prometer. | Implementado |

**Decisão de projeto.** O enunciado pedia exclusão lógica com uma coluna
`excluido_em`. Isso exigiria acrescentar `AND excluido_em IS NULL` a cada uma
das ~22 consultas que leem coleção — e é o tipo de mudança ampla que as regras
de trabalho deste backlog pedem para evitar. Pior: esquecer uma consulta não
quebra nada de forma visível; ela apenas passa a enxergar coleção excluída, e o
usuário consegue, por exemplo, adicionar uma foto a uma coleção que está na
lixeira. Com o retrato guardado à parte, a linha some de verdade e **nenhuma**
consulta precisa saber que a lixeira existe. O resultado para quem usa é o
mesmo; o risco de bug silencioso, não.

### Inicialização do servidor

Os modelos de busca eram carregados na importação: por ~30 segundos o Flask não
tinha começado a atender e o navegador não recebia nem a tela de login. O
usuário via "não foi possível acessar este site" e concluía que o programa não
tinha aberto.

| ID | Requisito | Situação |
|---|---|---|
| **RF-169** | O servidor deve atender em **menos de 2 segundos**, antes de os modelos estarem carregados. Medido: 29,70s → ~2,2s. | Implementado |
| **RF-170** | Os modelos devem carregar em segundo plano, sem bloquear o atendimento. | Implementado |
| **RF-171** | O modelo de **texto** deve carregar antes do resto. É ele que destrava a busca escrita, que é o que o usuário faz assim que abre o programa. | Implementado |
| **RF-172** | Nada pesado pode voltar para o nível do módulo. Medidos individualmente: modelos ~12s, scikit-learn ~4,8s, SDK do Claude ~3s. Há teste que falha se algum voltar. | Implementado |
| **RF-173** | `GET /api/health` deve informar o estado de cada modelo (`carregando`, `pronto`, `indisponivel`) **sem exigir sessão** — a espera acontece na tela de login, antes de qualquer sessão existir. | Implementado |
| **RF-174** | Buscar antes da carga terminar deve responder **503** com mensagem pedindo para tentar de novo em instantes — nunca lista vazia com 200, que o usuário lê como "minhas fotos não estão indexadas". | Implementado |
| **RF-175** | Depois que a carga termina sem sucesso, a mensagem deve **parar de mandar esperar** e dizer o que fazer. Esperar não resolve mais. | Implementado |
| **RF-176** | Nenhuma mensagem ao usuário pode citar nome de modelo. A mensagem anterior dizia "SBERT indisponível". | Corrigido |
| **RF-177** | A interface deve exibir aviso enquanto a busca se prepara, e removê-lo sozinha ao terminar. O aviso não pode bloquear clique. | Implementado |
| **RF-178** | Se os modelos já estiverem carregados, nenhum aviso deve aparecer — o caso comum é abrir o programa com o servidor já rodando. | Implementado |
| **RF-179** | A fila de indexação deve esperar os modelos. Sem isso os primeiros arquivos entrariam sem representação e ficariam invisíveis para a busca, sem sinal nenhum de erro. | Implementado |

**Contrapartida aceita:** a busca escrita fica pronta ~35s depois de abrir, contra
~29,7s antes, porque a carga agora divide processador com o servidor. Em troca, o
resto da interface sai de inacessível para utilizável em 2 segundos.

### Capa das coleções

| ID | Requisito | Situação |
|---|---|---|
| **RF-151** | A listagem de coleções deve disparar um número de consultas **constante**, independente de quantas coleções o usuário tenha. Antes era uma consulta por coleção para montar o mosaico da capa: 51 idas ao banco remoto para 50 coleções. | Corrigido |
| **RF-152** | A ordem das capas dentro de uma coleção deve ser estável entre recarregamentos. Sem ordenação explícita o mosaico mudava de arranjo sem nada ter mudado. | Corrigido |
| **RF-153** | A consulta das capas parte de uma tabela sem dono e precisa filtrar pelo usuário. Sem isso a capa de uma coleção alheia entraria no mosaico, expondo caminho de arquivo de outra pessoa. | Corrigido |

---

## 5. Critérios de aceite

Formato Dado/Quando/Então. Todos verificáveis manualmente com o app rodando.

### Busca

**CA-001 — Limpeza do campo**
Dado que o usuário digitou `montanhas neve suíça` no campo de busca;
Quando clicar no ícone `×`;
Então o campo deve ficar vazio imediatamente;
E o cursor deve estar no campo;
E o usuário deve conseguir digitar `praias brasil` sem apagar nada manualmente.
*Cobre RF-001, RF-003, RF-004.*

**CA-002 — Visibilidade do botão**
Dado que o campo de busca está vazio;
Então o ícone `×` não deve estar visível;
Quando o usuário digitar um único caractere;
Então o ícone deve aparecer;
Quando o usuário apagar esse caractere com `Backspace`;
Então o ícone deve desaparecer.
*Cobre RF-001, RF-002.*

**CA-003 — Sem efeitos colaterais**
Dado que o usuário fez uma busca e a lista de resultados está na tela;
Quando clicar no ícone `×`;
Então a página não deve recarregar;
E nenhuma requisição a `/api/search` deve ser disparada;
E os resultados exibidos devem permanecer na tela.
*Cobre RF-005, RF-006.*

**CA-004 — Teclado**
Dado que o campo contém texto e está focado;
Quando o usuário pressionar `Tab` e em seguida `Enter`;
Então o campo deve ser limpo;
E nenhuma busca deve ser disparada.
*Cobre RF-007.*

**CA-005 — Sincronia com limpeza programática**
Dado que o campo contém texto e o ícone `×` está visível;
Quando o usuário clicar no logo `SEARCH+` (que executa `voltarParaHomeSmooth()`);
Então o campo deve ficar vazio;
E o ícone `×` deve desaparecer junto.
*Cobre RF-010.*

**CA-006 — Histórico**
Dado que o dropdown de buscas recentes está aberto e o campo contém texto;
Quando o usuário clicar no ícone `×`;
Então o campo deve ser limpo;
E o clique não pode ser perdido pelo fechamento do dropdown.
*Cobre RF-011.*

**CA-007 — Responsivo**
Dado o navegador com largura de 500 px, onde `.search-box` empilha em coluna;
Quando o campo contiver texto;
Então o ícone `×` deve permanecer dentro dos limites do campo;
E não pode cobrir o botão `Buscar` nem o botão `📷`.
*Cobre RF-008, RF-009.*

### Seleção

**CA-008 — Seleção ≠ favorito**
Dado um resultado de busca não favoritado;
Quando o usuário marcar a caixa de seleção;
Então o card deve mostrar estado de selecionado;
E o ícone de favorito deve permanecer no estado "não favoritado";
E `GET /api/favorites` não deve passar a listar esse arquivo.
*Cobre RF-013, RF-014, RF-015.*

**CA-009 — Seleção sobrevive ao filtro**
Dado que o usuário selecionou 3 imagens com o filtro "Tudo";
Quando trocar para o filtro "Imagens" e voltar para "Tudo";
Então as mesmas 3 imagens devem continuar marcadas;
E o contador deve continuar exibindo 3.
*Cobre RF-019.*

**CA-010 — Nova busca zera a seleção**
Dado que há itens selecionados;
Quando o usuário executar uma nova busca;
Então a seleção deve estar vazia;
E a barra de ações da seleção não deve estar visível.
*Cobre RF-020.*

### Coleções

**CA-011 — Adição em lote**
Dado que o usuário selecionou 5 imagens;
Quando escolher "Adicionar à coleção" e selecionar `Arquitetura Moderna`;
Então as 5 imagens devem constar na coleção;
E a contagem da coleção deve aumentar em 5.
*Cobre RF-026.*

**CA-012 — Sem duplicação**
Dado que a imagem `foto_A` já está na coleção `Paisagens`;
Quando o usuário adicionar `foto_A` a `Paisagens` novamente;
Então a operação não deve retornar erro;
E a coleção deve continuar contendo `foto_A` uma única vez;
E o usuário deve ser informado de que o item já estava na coleção.
*Cobre RF-027, RF-028.*

**CA-013 — Remoção não destrói arquivo**
Dado que `foto_B` está numa coleção;
Quando o usuário removê-la da coleção;
Então `foto_B` deve sumir da coleção;
E o arquivo deve continuar existindo no disco;
E deve continuar aparecendo nos resultados de busca.
*Cobre RF-029.*

### Exportação

**CA-014 — Exportação bem-sucedida**
Dado que a coleção `Natureza` contém 12 imagens válidas no disco;
Quando o usuário acionar "Exportar coleção" e escolher `D:\Fotos`;
Então deve ser criada a pasta `D:\Fotos\Natureza`;
E ela deve conter 12 arquivos;
E os arquivos originais devem permanecer intactos em suas pastas de origem;
E a interface deve exibir "12 imagens salvas" e o caminho da pasta.
*Cobre RF-037, RF-044, RF-051.*

**CA-015 — Coleção vazia**
Dado que a coleção `Rascunhos` não tem itens;
Quando o usuário acionar "Exportar coleção";
Então o seletor de pasta não deve abrir;
E deve ser exibida mensagem informando que a coleção está vazia.
*Cobre RF-034.*

**CA-016 — Nome de coleção com caracteres inválidos**
Dado que existe a coleção `Férias 2024/2025: praia`;
Quando ela for exportada;
Então a pasta criada deve ter um nome válido no Windows (sem `/` nem `:`);
E a exportação deve concluir sem erro.
*Cobre RF-038.*

**CA-017 — Pasta de destino já existe**
Dado que `D:\Fotos\Natureza` já existe com arquivos dentro;
Quando o usuário exportar `Natureza` para `D:\Fotos`;
Então deve ser criada `D:\Fotos\Natureza (1)`;
E nenhum arquivo dentro de `D:\Fotos\Natureza` pode ser alterado ou apagado.
*Cobre RF-041, RF-043.*

**CA-018 — Nomes de arquivo repetidos**
Dado que a coleção contém dois arquivos chamados `IMG_0001.jpg`, vindos de pastas monitoradas diferentes;
Quando a coleção for exportada;
Então a pasta de destino deve conter `IMG_0001.jpg` e `IMG_0001_1.jpg`;
E cada um deve ter o conteúdo do respectivo original.
*Cobre RF-042, RF-047.*

**CA-019 — Arquivo sumiu do disco**
Dado que a coleção contém 10 imagens e 2 delas foram movidas para outra pasta depois da indexação;
Quando a coleção for exportada;
Então 8 arquivos devem ser copiados;
E a exportação deve concluir sem travar;
E o resumo deve indicar 2 falhas com o motivo "arquivo não encontrado" e os nomes correspondentes.
*Cobre RF-052, RF-053.*

**CA-020 — Progresso**
Dado que uma coleção com 12 imagens está sendo exportada;
Então a interface deve exibir o avanço de forma incremental (ex.: `8 de 12`);
E o valor exibido nunca pode retroceder nem exceder o total.
*Cobre RF-049, RF-050.*

**CA-021 — Destino sem permissão de escrita**
Dado que o usuário escolheu uma pasta na qual não tem permissão de escrita;
Quando a exportação for iniciada;
Então nenhuma cópia deve ser tentada;
E deve ser exibida mensagem em linguagem comum explicando que não foi possível gravar naquela pasta;
E nenhum *traceback* pode aparecer na interface.
*Cobre RF-054, RF-055.*

**CA-022 — Cancelamento**
Dado que uma exportação de 200 imagens está em andamento;
Quando o usuário cancelar;
Então a cópia deve parar em no máximo um arquivo após o comando;
E os arquivos já copiados devem permanecer no destino;
E o usuário deve ser informado de quantos foram copiados antes do cancelamento.
*Cobre RF-056.*

**CA-023 — Abrir pasta**
Dado que uma exportação terminou com sucesso;
Quando o usuário acionar "Abrir pasta";
Então o Explorer deve abrir exibindo a pasta criada.
*Cobre RF-058.*

### Paridade

**CA-024 — Mock e documentação em sincronia**
Dado que os endpoints de exportação foram implementados em `backend/app.py`;
Quando `pytest tests/integration/test_paridade_mock.py` for executado;
Então ele deve passar;
E nenhuma rota `/api/` pode existir só no backend real, só no mock, ou só no `docs/API.md`.
*Cobre RF-061, RF-062.*

### Seleção em massa e exportação imediata

**CA-026 — Selecionar tudo**
Dado que uma pesquisa retornou 7 imagens elegíveis;
Quando o usuário acionar "Selecionar tudo";
Então as 7 devem ficar marcadas;
E o contador deve exibir "7 selecionadas";
E o botão deve passar a exibir "Desmarcar tudo".
*Cobre RF-065, RF-067, RF-069.*

**CA-027 — Completar seleção parcial**
Dado que 1 de 7 imagens está marcada manualmente;
Quando o usuário acionar "Selecionar tudo";
Então as 7 devem ficar marcadas — a já marcada não pode ser desmarcada.
*Cobre RF-068.*

**CA-028 — Sincronia com a seleção individual**
Dado que todas as 7 estão selecionadas e o botão exibe "Desmarcar tudo";
Quando o usuário desmarcar uma imagem no card;
Então o contador deve exibir "6 selecionadas";
E o botão deve voltar a "Selecionar tudo";
E ao remarcar essa imagem, deve voltar a "Desmarcar tudo".
*Cobre RF-070.*

**CA-029 — Sem resultados**
Dado que a pesquisa não retornou nada;
Então a barra de ações dos resultados não deve estar visível.
*Cobre RF-071.*

**CA-030 — Exportação imediata**
Dado que o usuário adicionou imagens a uma coleção;
Quando a adição for concluída;
Então deve ser oferecida a exportação daquela coleção;
E aceitar deve acionar o mesmo fluxo de exportação do modal de Coleções.
*Cobre RF-073, RF-075.*

**CA-031 — Recusar preserva tudo**
Dado que a oferta de exportação foi exibida;
Quando o usuário escolher continuar pesquisando;
Então nenhuma exportação deve ser iniciada;
E a coleção deve manter todas as imagens adicionadas.
*Cobre RF-074, RF-078.*

### Pasta vinculada

**CA-032 — Pergunta uma vez só**
Dado que o usuário criou uma coleção e escolheu "enviar sempre, sem perguntar";
Quando adicionar imagens a essa coleção três vezes seguidas;
Então nenhuma confirmação deve ser exibida em nenhuma das três;
E as imagens devem estar na pasta vinculada.
*Cobre RF-081, RF-088.*

**CA-033 — Modo perguntar**
Dado que a coleção está no modo "perguntar antes";
Quando o usuário adicionar imagens;
Então deve ser exibida uma confirmação por adição;
E recusar não pode remover as imagens da coleção.
*Cobre RF-089, RF-093.*

**CA-034 — Modo manual não envia nada**
Dado que a coleção não tem pasta vinculada;
Quando o usuário adicionar imagens;
Então nada deve ser copiado e nada deve ser perguntado;
E o botão Exportar deve continuar funcionando.
*Cobre RF-084, RF-090.*

**CA-035 — Espelho, não acumulador**
Dado que a imagem `a.jpg` já está na pasta vinculada;
Quando a sincronia rodar novamente para essa imagem;
Então nenhum arquivo `a_1.jpg` deve ser criado;
E o resultado deve contá-la como já existente.
*Cobre RF-092.*

**CA-036 — Só o que é novo**
Dado uma coleção de 300 imagens com pasta vinculada em modo `auto`;
Quando o usuário adicionar 1 imagem;
Então a sincronia deve copiar 1 arquivo, não 301.
*Cobre RF-091.*

**CA-037 — Pasta sumiu do disco**
Dado que a pasta vinculada foi apagada ou movida;
Quando uma sincronia for disparada;
Então deve ser exibida mensagem orientando a vincular outra pasta;
E a coleção deve continuar vinculada — o sistema não desvincula sozinho;
E as imagens devem permanecer na coleção.
*Cobre RF-094.*

**CA-039 — Exportar dá memória à coleção**
Dado uma coleção com 2 imagens exportada para uma pasta;
Quando o usuário adicionar uma terceira imagem;
Então a coleção deve continuar apontando para a pasta exportada;
E a terceira imagem deve poder ir para lá — sozinha ou após confirmação, conforme o modo.
*Cobre RF-097.*

**CA-040 — Abrir pasta exportada**
Dado uma coleção com pasta no disco;
Quando o usuário abrir a coleção;
Então deve haver um botão "Abrir pasta exportada";
E acioná-lo deve abrir a pasta no Explorer.
*Cobre RF-098, RF-099.*

**CA-041 — Excluir coleção mantendo a pasta**
Dado uma coleção que gerou uma pasta com arquivos;
Quando o usuário excluir a coleção e escolher manter as pastas;
Então a coleção deve ser excluída;
E a pasta e seus arquivos devem permanecer no disco.
*Cobre RF-101, RF-104.*

**CA-042 — Apagar somente uma pasta**
Dado uma coleção que gerou duas pastas;
Quando o usuário marcar apenas a segunda e confirmar as duas etapas;
Então somente a segunda deve ser apagada;
E a primeira deve permanecer intacta com seus arquivos.
*Cobre RF-103, RF-105.*

**CA-043 — Segunda etapa é obrigatória**
Dado que o usuário marcou uma pasta e acionou apagar;
Então nada deve ser apagado no primeiro acionamento;
E deve ser exibido o aviso com a contagem de pastas e arquivos;
E só o segundo acionamento executa.
*Cobre RF-105, RF-106.*

**CA-056 — Favorito visível**
Dado um resultado não favoritado exibindo `♡`;
Quando o usuário clicar no botão;
Então ele deve passar a exibir `♥` preenchido, em cor de destaque e com fundo tingido;
E `aria-pressed` deve virar `true`;
E clicar de novo deve voltar ao estado anterior.
*Cobre RF-147, RF-148, RF-150.*

**CA-053 — Remoção espelhada**
Dado uma coleção em modo "manter a pasta igual";
Quando o usuário remover uma imagem da coleção;
Então a cópia deve ser apagada das pastas que recebem;
E o arquivo original deve permanecer intacto;
E em modo manual nada deve ser apagado.
*Cobre RF-136, RF-137.*

**CA-054 — Status mostra o que falta**
Dado uma coleção de 4 imagens com 2 copiadas para a pasta;
Quando o usuário abrir "Status da pasta";
Então deve ver "2 na pasta" e "2 faltando", com os nomes;
E deve poder copiar as faltantes dali.
*Cobre RF-142, RF-145.*

**CA-055 — Travessia de caminho recusada**
Dado um pedido de remoção com o nome `..\importante.txt`;
Quando ele for processado;
Então nada fora da pasta espelho pode ser apagado.
*Cobre RF-138.*

**CA-051 — Trocar o modo depois**
Dado uma coleção configurada como "perguntar antes";
Quando o usuário abrir Configurações;
Então a opção em vigor deve estar marcada como atual;
E escolher outra deve salvar e refletir nas adições seguintes.
*Cobre RF-131, RF-133.*

**CA-052 — Enviar para todas de uma vez**
Dado uma coleção com duas pastas e apenas uma marcada;
Quando o usuário acionar "Enviar para todas as pastas";
Então as duas devem passar a receber;
E o mesmo controle deve então oferecer desmarcar todas.
*Cobre RF-135.*

**CA-048 — Espelhar em duas pastas**
Dado uma coleção com duas pastas exportadas, ambas marcadas para receber;
Quando o usuário adicionar uma imagem;
Então a imagem deve ser copiada para as duas pastas;
E o resultado deve informar 2 cópias.
*Cobre RF-123, RF-125.*

**CA-049 — Nenhuma pasta recebendo**
Dado que o usuário desmarcou todas as pastas;
Quando adicionar imagens à coleção;
Então nada deve ser copiado;
E as pastas devem continuar registradas e abríveis.
*Cobre RF-124.*

**CA-050 — Uma pasta sumida não bloqueia as outras**
Dado duas pastas marcadas e uma delas apagada do disco;
Quando a sincronia rodar;
Então a cópia deve acontecer na pasta que restou;
E a operação não deve falhar.
*Cobre RF-127.*

**CA-045 — Prefixo preservado nas re-exportações**
Dado a coleção "Natureza" já exportada uma vez;
Quando o usuário exportar de novo sem escolher complemento;
Então a nova pasta deve se chamar "Natureza_2";
E ao escolher o complemento "backup", deve se chamar "Natureza_backup".
*Cobre RF-112, RF-113, RF-114.*

**CA-046 — Re-exportar não muda o destino sozinho**
Dado que as fotos da coleção vão para "Natureza";
Quando o usuário exportar para uma segunda pasta;
Então "Natureza" deve continuar recebendo até o usuário escolher outra.
*Cobre RF-117.*

**CA-047 — Escolher qual pasta abrir**
Dado uma coleção com três pastas exportadas;
Quando o usuário acionar "Abrir pasta exportada";
Então as três devem ser listadas com caminho e contagem de arquivos;
E a que recebe as fotos deve estar marcada;
E abrir qualquer uma deve ser possível.
*Cobre RF-119, RF-120, RF-121.*

**CA-044 — Caminho não registrado é recusado**
Dado um caminho que existe no disco mas não foi gerado pelo app;
Quando ele for enviado para exclusão;
Então nada deve ser apagado;
E a resposta deve marcá-lo como não autorizado.
*Cobre RF-107.*

**CA-038 — Vínculo alterável**
Dado uma coleção vinculada em modo `auto`;
Quando o usuário desvincular a pasta;
Então a coleção deve voltar ao modo `manual`;
E adições seguintes não devem copiar nada.
*Cobre RF-086.*

**CA-025 — Mock não escreve em disco**
Dado o servidor mock rodando (`py backend/mock_server.py`);
Quando uma exportação for acionada pela interface;
Então o fluxo completo deve ser exercitável — progresso, resumo e erros;
E nenhuma pasta pode ser criada e nenhum arquivo copiado no disco.
*Cobre RF-063, RF-064.*

---

## 6. Rastreabilidade

| Área | RFs | Critérios de aceite |
|---|---|---|
| Limpar busca | RF-001 … RF-012 | CA-001 … CA-007 |
| Seleção | RF-013 … RF-021 | CA-008 … CA-010 |
| Coleções | RF-022 … RF-032 | CA-011 … CA-013 |
| Exportação | RF-033 … RF-060 | CA-014 … CA-023 |
| Paridade do repositório | RF-061 … RF-064 | CA-024, CA-025 |

### Requisitos que já estão implementados

`RF-015`, `RF-021`, `RF-022`, `RF-023`, `RF-024`, `RF-025`, `RF-027`,
`RF-029`, `RF-030`, `RF-031`, `RF-032`. Estão listados por serem
pré-condições das features novas e por precisarem de teste de regressão — não
representam trabalho de implementação.

### Conflitos identificados e resolvidos durante a análise

| Conflito | Resolução |
|---|---|
| "Limpar o campo" poderia significar limpar o texto **ou** voltar à home. | RF-006: limpa só o texto. Voltar à home continua sendo o clique no logo. |
| O pedido original previa "download falhou" e "internet indisponível". | Não se aplicam: as imagens são locais. Substituídos por arquivo ausente, permissão negada e disco cheio (RF-052, RF-054). |
| "Favoritar ≠ selecionar" versus a UI atual, onde adicionar a coleção parte do painel lateral de **um** arquivo. | RF-013 e RF-026 introduzem a seleção múltipla; o caminho atual de um-por-um (RF-025) permanece funcionando em paralelo. |
| Dedup por conteúdo versus dedup por identidade. | RF-027 resolve por identidade (`files.id`), garantido pelo banco. Dedup por conteúdo fica de fora (RF-047) e vira decisão pendente `D-4`. |
| RF-002 (ocultar o `×`) versus "ficar desabilitado", ambos permitidos no pedido. | Ocultar. O projeto não tem padrão de botão desabilitado; ocultar é o que ele já faz com `#filterBarContainer` e `#colecaoConteudo`. |

---

## 7. Decisões pendentes antes da implementação

| # | Decisão | Impacto se adiada |
|---|---|---|
| **D-1** | `Escape` no campo de busca deve limpar o texto? Hoje `Escape` é "fechar janela" em todo o app (`script.js:2358`). | Baixo. Pode entrar depois sem retrabalho. |
| **D-2** | A pasta de destino da exportação deve ser lembrada entre exportações, como chave nova em `users.config_json` (`_DEFAULT_CFG`, `backend/app.py:746`)? | Médio. Muda a assinatura do endpoint de exportação. Melhor decidir antes. |
| **D-3** | Exportar **apenas imagens** ou **todos os tipos** presentes na coleção? Coleções aceitam PDF, DOCX, MP4 etc. (`_EXT_ALL`, `backend/app.py:3058`). O fluxograma fala em fotos. | **Alto.** Define o filtro da consulta de exportação e o texto do resumo. |
| **D-4** | Deduplicar arquivos de conteúdo idêntico na exportação (exigiria *hash*, que a tabela `files` não guarda)? | Médio. Adiciona coluna e custo de I/O; RF-047 assume "não" por ora. |
| **D-5** | Manter suporte apenas a Windows (tkinter + `explorer`) ou já abstrair a camada de sistema operacional? | Médio. O README já declara Windows como requisito; abstrair depois é possível, mas mais caro. |
