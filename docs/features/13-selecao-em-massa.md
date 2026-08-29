# Feature — Selecionar tudo e exportação imediata

**Data:** 25/08/2026
**Branch:** `feature/selecionar-todas-e-exportacao-imediata`
**Requisitos:** RF-065 … RF-079 · CA-026 … CA-031 ·
[`../09-requisitos-funcionais.md`](../09-requisitos-funcionais.md)
**Status:** implementado.

Evolução de fluxo sobre [`12-colecoes-exportacao.md`](12-colecoes-exportacao.md).
Não é uma feature nova: são dois atalhos dentro do fluxo que já existia.

---

## 1. Problema

O fluxo montado na feature anterior funciona, mas cobra pedágio nas duas pontas.

**Na entrada:** montar uma coleção com os resultados de uma busca exige marcar
imagem por imagem. Vinte resultados, vinte cliques — e a busca semântica do
Search+ costuma devolver justamente um conjunto coerente, que o usuário quer
inteiro.

**Na saída:** depois de adicionar, exportar exigia abrir Coleções, achar a
coleção no mosaico, entrar nela e só então clicar em exportar. Quatro passos
para uma intenção que o usuário já tinha formado no passo anterior.

```
ANTES                            DEPOIS
─────                            ──────
selecionar imagem 1              pesquisar
selecionar imagem 2                  ↓
selecionar imagem 3              selecionar tudo
   ⋮  (× N)                          ↓
adicionar à coleção              adicionar à coleção
ir para Coleções                     ↓
achar a coleção                  exportar coleção
entrar nela
exportar
```

---

## 2. O que já existia (e foi reutilizado)

Nada de seleção, coleção ou exportação foi recriado. O que a feature faz é
alcançar peças que já estavam prontas.

| Peça existente | Onde | Como é aproveitada |
|---|---|---|
| `_selecionados` — `Set` de `files.id` | `script.js:2458` | Continua sendo a **única** fonte de verdade da seleção. "Selecionar tudo" só faz `add`/`delete` em massa nele. |
| `alternarSelecao()` | `script.js:2460` | Intocada. A seleção individual continua funcionando exatamente igual. |
| `atualizarBarraSelecao()` | `script.js:2480` | Ganhou uma chamada a `atualizarAcoesResultados()`; a lógica da barra flutuante não mudou. |
| `limparSelecao()` | `script.js:2496` | Intocada — já era o "desmarcar tudo" global. |
| `adicionarAColecao()` | `script.js:2816` | Ganhou a oferta de exportação ao final. O envio em lote já existia. |
| `POST /api/collections/<id>/files` | `backend/app.py:2633` | **Sem alteração.** Já aceitava `file_ids` em lote e já devolvia `adicionados`/`ja_existiam`. |
| `exportarColecao()` | `script.js:2878` | **Sem alteração.** A exportação imediata só aponta `_colecaoAtual` e chama esta função. |
| `confirmarAcao()` | `script.js:94` | Reutilizado como o "modal de confirmação" da oferta. Nenhum componente novo de notificação. |

**Backend: zero linhas novas de endpoint.** A única mudança em `backend/app.py`
foi a correção de um bug em `_sanitizar_nome` que os testes novos revelaram
(ver §7).

---

## 3. Selecionar tudo

### 3.1 O que "tudo" significa

**Os resultados da busca atual que passam pelo filtro ativo.** Não o acervo.

Esta definição foi verificada no código, não presumida:

- `POST /api/search` devolve a lista completa numa resposta única
  (`window.resultadosAtuais = dados.resultados`, `script.js:1536`).
- Não há paginação, `offset`, `limit`, *scroll* infinito nem virtualização em
  nenhum ponto do caminho da busca.
- `renderizarResultados()` desenha **todos** os itens filtrados de uma vez.

Logo "carregado", "exibido" e "retornado pelo servidor" são o mesmo conjunto —
a ambiguidade que o pedido levantava não existe nesta arquitetura. Se algum dia
entrar paginação, esta seção é o ponto a revisitar.

### 3.2 A função-chave

```js
function resultadosVisiveis() { … }
```

Extraída de dentro de `renderizarResultados()`, que aplicava o filtro inline.
O motivo é a consistência exigida por RF-070: se a renderização e o
"selecionar tudo" filtrassem cada um por conta própria, bastaria alguém mexer
em uma para o contador passar a descrever um conjunto diferente do que está na
tela. Agora ambos leem da mesma fonte.

### 3.3 Estado do botão

| Situação | Rótulo | `aria-pressed` |
|---|---|---|
| Nada selecionado | ☑ Selecionar tudo | `false` |
| Seleção parcial | ☑ Selecionar tudo | `false` |
| Tudo selecionado | ☒ Desmarcar tudo | `true` |

Com seleção parcial o clique **completa** a seleção (RF-068) — não inverte.
Inverter perderia o trabalho manual já feito pelo usuário.

### 3.4 Por que o DOM não é reconstruído

`sincronizarCardsComSelecao()` percorre os cards e ajusta classe, texto e
`aria-checked` de cada um. A alternativa óbvia seria chamar
`renderizarResultados()`, mas ela faz `mGrid.innerHTML = …`: com 200 resultados
isso recria 200 cards, recarrega 200 `<img>` e joga fora a posição de rolagem —
tudo para mudar uma classe CSS.

Medição com 1000 itens: **18,5 ms**.

### 3.5 Desmarcar respeita o filtro

"Desmarcar tudo" remove da seleção apenas os itens **visíveis**. Uma seleção
feita sob outro filtro permanece — coerente com RF-019, que já exigia que a
seleção sobrevivesse à troca de filtro.

---

## 4. Exportação imediata

### 4.1 Onde entra

Ao final de `adicionarAColecao()`, depois do *toast* de sucesso e da limpeza da
seleção. Vale para os dois caminhos, porque ambos terminam nela:

- coleção existente → `abrirSeletorColecao()` → `adicionarAColecao()`
- coleção nova → `criarColecaoEAdicionar()` → `adicionarAColecao()`

Um único ponto de integração cobre RF-073 nos dois casos.

### 4.2 Como reutiliza a exportação

```js
_colecaoAtual = { id: colId, nome };
await exportarColecao();
```

Duas linhas. `exportarColecao()` já lia `_colecaoAtual` porque é assim que o
modal de Coleções opera — a feature apenas aponta essa variável para a coleção
recém-atualizada. Todo o resto (seletor nativo de pasta, job em *background*,
barra de progresso, resumo com falhas, botão "Abrir pasta", cancelamento) vem
de graça e continua sendo código único.

### 4.3 A confirmação

Usa `confirmarAcao()`, o modal que substituiu o `confirm()` nativo no projeto:

```
┌─────────────────────────────────────────────┐
│ Coleção atualizada                          │
│                                             │
│ 15 imagens estão em "Arquitetura Moderna".  │
│ Quer exportar para uma pasta no seu         │
│ computador agora?                           │
│                                             │
│  [ Continuar pesquisando ]  [ Exportar ]    │
└─────────────────────────────────────────────┘
```

O total vem de `GET /api/collections/<id>`, relido após a adição — é o estado
**atual** exigido por RF-076. Se essa leitura falhar, a oferta ainda aparece,
só que sem o número: perder a contagem não justifica perder o atalho (RF-077).

### 4.4 Uma correção de contágio

`confirmarAcao()` reatribuía o texto do botão OK a cada chamada, mas nunca o do
botão Cancelar. Como o botão é um só no DOM, customizar "Cancelar" para
"Continuar pesquisando" teria vazado esse rótulo para **todas** as outras
confirmações do app — inclusive a de excluir coleção.

A função ganhou um quarto parâmetro opcional, com o padrão `'Cancelar'`, e
passou a reatribuir o rótulo sempre. Retrocompatível: as chamadas existentes
não mudaram.

---

## 5. Interface

```
                    Resultados
        12 resultados · 8 selecionadas
             [ ☑ Selecionar tudo ]
    ────────────────────────────────────────
      [imagem]   [imagem]   [imagem]
```

A barra fica entre o título e o grid, alinhada à largura do grid
(`max-width: 1400px`, o mesmo de `.results-grid`). A barra flutuante de ações
em lote, que já existia, permanece no rodapé — as duas não competem: uma conta
e seleciona, a outra age sobre a seleção.

**Acessibilidade** (verificada em execução):

| Item | Estado |
|---|---|
| `<button type="button">` real | ✅ |
| Recebe foco por `Tab` | ✅ |
| `aria-pressed` acompanha o estado | ✅ |
| `aria-label` e `title` mudam junto com o rótulo | ✅ |
| Texto visível, não só ícone | ✅ |
| `:focus-visible` com contorno | ✅ |

**Responsividade:** alvo de 156 × 37 px no desktop e 156 × 44 px abaixo de
640 px (mínimo recomendado para toque). `flex-wrap` deixa a contagem e o botão
empilharem. Sem *overflow* horizontal em 1440 px nem em 375 px.

---

## 6. Casos de borda verificados

Todos exercitados no navegador, contra o `mock_server`:

| # | Caso | Resultado |
|---|---|---|
| 1 | 0 resultados | Barra de ações oculta |
| 2 | 1 resultado | "1 resultado · 1 selecionada" — singular correto |
| 3 | 1000 resultados | 18,5 ms |
| 4 | Seleção parcial + selecionar tudo | 1 → 7, nenhuma perdida |
| 5 | Tudo selecionado | Botão vira "Desmarcar tudo" |
| 6 | Desmarcar uma após selecionar tudo | 7 → 6, botão volta; remarcar → 7, botão volta |
| 7 | Coleção nova + adicionar tudo | Oferta de exportação aparece |
| 8 | Coleção existente | Oferta aparece com o total atualizado |
| 9 | Recusar a exportação | `_colecaoAtual` intacto, coleção com 7 itens |
| 10 | Falha na exportação | Tratada pelo fluxo existente; coleção preservada |
| 11 | Re-adicionar as mesmas imagens | Total continua 7 — sem duplicação |
| — | Troca de filtro com seleção ativa | Seleção preservada |

Em todos, `_selecionados.size` bateu com a contagem de `.btn-sel-abs.is-sel` e
de `.card-selecionado` no DOM — a inconsistência que RF-070 proíbe não ocorreu.

---

## 7. Um bug encontrado pelos testes

`_sanitizar_nome("///:::***")` devolvia `_________` em vez do nome padrão.

A guarda era `return limpo or padrao`, que só captura string vazia. Um nome
formado apenas por caracteres inválidos vira uma sequência de `_` — tecnicamente
válida no Windows, e completamente inútil para quem abrir a pasta.

Corrigido: sem nenhum caractere alfanumérico restante, usa-se o padrão
(`colecao_<id>`). É o que RF-039 pretendia.

O teste que pegou isso é
`test_usa_padrao_quando_sobra_vazio`, em `tests/unit/test_exportacao_colecao.py`.

---

## 8. Testes

O projeto **não usa Jest nem ESLint** — não há `package.json`, e o frontend é
JS puro sem *build step*. A infraestrutura de teste é `pytest` e `locust`,
descrita em [`../TESTING.md`](../TESTING.md).

### Unitários — 58 novos

| Arquivo | Testes | Cobre |
|---|---|---|
| `tests/unit/test_exportacao_colecao.py` | 44 | Sanitização, colisão de nomes e pastas, autorização de origem, cópia real em disco, falhas por item, cancelamento |
| `tests/unit/test_colecao_lote.py` | 14 | Normalização de `file_ids`, idempotência, isolamento por usuário, remoção em lote |

Os testes de exportação tocam o disco de verdade (`tmp_path`): o valor da
feature está no efeito colateral, então verificar só o retorno não provaria
nada.

### Carga — 2 tarefas novas

Em `tests/load/locustfile.py`:

- `selecionar_tudo_e_adicionar_em_lote` — busca, cria coleção, envia **todos**
  os ids num lote, relê a coleção (como a confirmação faz) e limpa. É a
  requisição de maior *payload* do produto: a lista cresce com o tamanho do
  resultado.
- `readicionar_lote_ja_existente` — mede o caminho 100 % idempotente
  (`ON CONFLICT DO NOTHING` sem gravar nada) e **falha o teste** se
  `adicionados` não for 0, o que denunciaria duplicação sob concorrência.

Ambas limpam a coleção criada, para não acumular lixo entre execuções.

---

## 9. Arquivos alterados

| Arquivo | Mudança |
|---|---|
| `index.html` | Barra `#resultadosAcoes` com contagem e botão (+8 linhas) |
| `script.js` | `resultadosVisiveis()`, `todosVisiveisSelecionados()`, `alternarSelecionarTodos()`, `sincronizarCardsComSelecao()`, `atualizarAcoesResultados()`, `oferecerExportacaoImediata()`; 4º parâmetro em `confirmarAcao()` |
| `style.css` | `.resultados-acoes`, `.resultados-resumo`, `.btn-selecionar-todos` + regra móvel |
| `backend/app.py` | Correção do `_sanitizar_nome` (§7) — única mudança de backend |
| `tests/unit/test_exportacao_colecao.py` | Novo |
| `tests/unit/test_colecao_lote.py` | Novo |
| `tests/load/locustfile.py` | 2 tarefas + `import time` |
| `docs/09-requisitos-funcionais.md` | RF-065 … RF-079, CA-026 … CA-031 |
| `docs/README.md` | Índice |

---

## 10. Limitações e decisões

| # | Decisão | Motivo |
|---|---|---|
| **L-1** | "Tudo" = resultados visíveis, não o acervo. | É o que a arquitetura permite hoje. Selecionar o acervo inteiro exigiria endpoint novo e mudaria o significado da ação. |
| **L-2** | A seleção continua efêmera, em memória. | RF-018 já definia assim. Persistir seria outra feature. |
| **L-3** | A oferta de exportação aparece a **cada** adição. | Recusar custa um clique. Suprimi-la exigiria preferência persistente — complexidade desproporcional. Reavaliar se incomodar no uso real. |
| **L-4** | `GET /api/collections/<id>` traz a lista inteira só para contar. | Já é como a tela de coleções funciona; endpoint só de contagem seria peça nova para pouco ganho. Vale rever se as coleções crescerem muito. |
| **L-5** | Sem teste automatizado do JS. | O projeto não tem *runner* de JS. Introduzir Node só para isso contraria "não introduza bibliotecas sem necessidade". A verificação foi feita no navegador, contra o mock, e está registrada em §6. |
