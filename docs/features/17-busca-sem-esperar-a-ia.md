# Feature — A busca responde sem esperar a IA

**Data:** 21/09/2026
**Branch sugerida:** `feature/busca-sem-esperar-a-ia` (ver [`../07-git-fluxo.md`](../07-git-fluxo.md))
**Status:** **especificação**. Escrito antes do código. O texto usa "deve"/"deverá"
de propósito — descreve o contrato que a implementação precisa cumprir.
**Escopo:** `backend/app.py`, `backend/mock_server.py`, `docs/API.md`, `script.js`.
Altera o backend **e** o contrato da API, o que o [`../../AGENTS.md`](../../AGENTS.md)
pede que seja proposto antes de aplicado — é o que este documento é.

**Pré-requisito:** a [feature 16](16-latencia-da-busca.md), etapas 0, 1 e 3, já
está aplicada. Esta é a etapa 4 daquele documento, separada porque mexe no
contrato.

---

## 1. O que sobrou depois da feature 16

As etapas 1 e 3 mudaram a **estrutura** da espera: as cinco descrições correm
juntas em vez de enfileiradas, e cada chamada tem teto de 20 s. Não eliminaram
a espera — a busca continua parada até a IA responder.

O melhor caso possível daquele desenho é o tempo de **uma** descrição mais o
re-rank. Enquanto a biblioteca não estiver descrita, isso acontece em quase toda
busca, e é justamente quando a pessoa está formando opinião sobre o produto.

A instrumentação da etapa 0 diz exatamente quanto sobrou:

```
[Busca] 8.1s — sql 0.4 | clip 0.2 | descricao 6.2 (5) | persistencia 0.3 | rerank 1.0
```

**Antes de implementar esta feature, rode uma busca por assunto novo e anote
essa linha.** Se `descricao` já estiver baixo e o `rerank` dominar, o problema
mudou de lugar e este documento ataca a coisa errada.

---

## 2. A ideia

A busca **responde na hora** com o que já sabe, e completa depois.

Isso é viável porque o motor **já pontua imagem sem descrição**. O
`blended = min(0.70, 0.85 * s_visual)` (`app.py`, bloco do blend) existe
exatamente para o caso "só tenho CLIP". Um resultado sem descrição já aparece
hoje — só aparece **depois** de esperar descrições que muitas vezes nem são
dele.

O usuário já espera por uma delas. A diferença é que passa a esperar **olhando
para os resultados**, e não para uma tela parada.

---

## 3. Desenho

### 3.1 O que a busca faz

1. Pontua e ordena com o que está no banco, como hoje.
2. **Não descreve nada.** Em vez disso, enfileira as candidatas no `_queue`,
   que já existe e já é consumido pelo `_process_worker`.
3. Responde imediatamente, dizendo **quais ids** foram para a fila.

O enfileiramento reusa o formato que o worker já consome:

```python
_queue.put({"path": f["caminho"], "nome": f["nome"], "ext": f["tipo"], "uid": uid})
```

Nenhuma estrutura nova. O worker já sabe descrever, gerar embedding e gravar.

### 3.2 O que o front faz

O padrão já está implementado: a barra de status bate a cada 2 s e a galeria se
atualiza sozinha quando a fila anda — foi o commit
`feat(home): a galeria acompanha a analise, sem precisar de F5`.

Aqui vale o mesmo, aplicado à tela de resultados: enquanto houver ids
pendentes, a busca é **refeita em segundo plano** e a lista é reordenada.

### 3.3 Por que refazer a busca, e não remendar o resultado

Tentador: quando uma descrição fica pronta, atualizar só aquele card.

Não serve. A descrição muda o **score** do item, e score muda **posição**.
Remendar um card no lugar onde ele está mostraria a descrição nova com a ordem
velha — pior que não atualizar, porque parece certo. Refazer a busca é mais
caro e é o único jeito de a ordem continuar verdadeira.

A segunda busca é barata: as descrições já estão em cache, então ela cai no
caminho de ~1 s que o `README.md` descreve.

---

## 4. Contrato da API

Esta é a parte que obriga o documento próprio.

`POST /api/search` ganha **um campo**, e nenhum muda de forma:

```json
{
  "resultados": [...],
  "tempo": 0.9,
  "consulta": "praia",
  "excluidos": [],
  "escopo": 0,
  "descrevendo": [12, 45, 78]
}
```

| Campo | Significado |
|---|---|
| `descrevendo` | Ids enfileirados para descrição **por causa desta busca**. Lista vazia quer dizer "nada pendente, o resultado é final". |

Regras:

- **`descrevendo` é sempre uma lista**, nunca ausente e nunca `null`. Um campo
  que às vezes não vem obriga todo consumidor a tratar dois casos.
- Um front que ignore o campo **continua funcionando**, com o comportamento de
  hoje menos a espera. É o que torna a mudança segura de mergear antes do
  front acompanhar.
- `mock_server.py` **deve** devolver o campo, mesmo que sempre vazio — ele não
  chama IA. Mock que diverge do backend é pior que não ter mock
  (`AGENTS.md`), e há teste de paridade.

---

## 5. O que pode dar errado

| Risco | Por quê | O que fazer |
|---|---|---|
| **Busca em laço** | A busca refeita enfileira de novo, responde `descrevendo` de novo, e o front refaz para sempre | Só reenfileirar id que ainda **não tem** descrição. Quando a fila drena, `descrevendo` vem vazio e o laço para sozinho |
| **Fila inundada** | Cada busca joga até 5 itens numa fila que a indexação também usa | Manter o teto de 5 por busca, e **não** enfileirar id que já está na fila |
| **A ordem "pula" na cara do usuário** | A segunda busca reordena enquanto a pessoa lê | Atualizar só quando a tela de resultados estiver visível, como `atualizarHomeSeCabe` já faz para a home |
| **Custo igual, sensação melhor** | As descrições continuam sendo chamadas pagas | É verdade e é aceitável: o objetivo é latência, não custo. Não vender isto como economia |
| **Resultado pior na primeira volta** | Sem descrição, imagem pontua só por CLIP | Já é o comportamento de hoje para tudo que está fora das 5 primeiras. A diferença é que agora aparece rápido e melhora sozinho |

---

## 6. Testes

**Novo: `tests/unit/test_busca_sem_esperar.py`**

| Teste | O que garante |
|---|---|
| A busca não chama a visão | Nenhuma chamada à API dentro do request |
| Candidatas sem descrição vão para a fila | O enfileiramento acontece |
| `descrevendo` traz os ids enfileirados | O contrato novo |
| Biblioteca descrita → `descrevendo` vazio | A condição de parada do laço |
| Id já descrito não é reenfileirado | O laço infinito |
| O teto de 5 por busca continua | Custo |
| O payload mantém os campos de hoje | Nada quebra no front atual |

**Paridade:** `test_paridade_mock.py` passa a cobrar `descrevendo` no mock.

**Carga:** com a IA fora do request, `SEARCHPLUS_LOAD_MAX_P95_IA_MS` (hoje
5000 ms) deixa de fazer sentido para a busca — ela passa a caber no limite
comum. Vale reduzir o limite em vez de deixá-lo folgado, senão ele para de
medir qualquer coisa.

---

## 7. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `backend/app.py` | Enfileirar em vez de descrever; campo `descrevendo` |
| `backend/mock_server.py` | Campo `descrevendo`, sempre `[]` |
| `docs/API.md` | Documentar o campo |
| `script.js` | Refazer a busca enquanto houver pendentes |
| `docs/10-requisitos-nao-funcionais.md` | Requisito de latência da busca passa a ser alcançável de verdade |
| `README.md` | A frase sobre a primeira busca deixa de valer |

**Não muda:** `schema.sql`, `index.html`, `style.css`.

---

## 8. Ordem sugerida

1. Medir e anotar a linha `[Busca]` de hoje — sem isso não há como provar nada
2. Backend: enfileirar, responder `descrevendo`, com os testes da seção 6
3. Mock e `docs/API.md` na mesma leva — a paridade é cobrada por teste
4. Front: refazer a busca enquanto houver pendentes
5. Medir de novo e comparar com o passo 1

Os passos 2 e 3 já entregam o ganho de latência mesmo sem o passo 4: a busca
responde rápido, e a precisão melhora na busca seguinte em vez de na mesma.
O passo 4 é o que faz a melhora aparecer sem o usuário digitar de novo.
