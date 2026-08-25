# Requisitos Funcionais — Limpar busca e Coleções/Exportação

**Data:** 25/08/2026
**Escopo:** duas funcionalidades novas — (1) botão de limpar o campo de busca;
(2) seleção de imagens, coleções e exportação para uma pasta local.
**Status:** especificação. Nenhum código de aplicação foi alterado.

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

Nada nesta seção existe hoje. Tudo é novo.

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
