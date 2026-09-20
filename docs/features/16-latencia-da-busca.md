# Feature — Reduzir o tempo de resposta da busca

**Data:** 12/09/2026
**Branch sugerida:** `feature/latencia-da-busca` (ver [`../07-git-fluxo.md`](../07-git-fluxo.md))
**Status:** **especificação**. Escrito antes do código. O texto usa "deve"/"deverá"
de propósito — ele descreve o contrato que a implementação precisa cumprir.
**Escopo:** `backend/app.py`. Esta feature **altera o backend**, o que o
[`../../AGENTS.md`](../../AGENTS.md) pede que seja proposto antes de aplicado —
é o que este documento é.

---

## 1. Problema

Uma busca por um assunto ainda não indexado leva **até 40 segundos** para
responder. Não é variação de rede: é o desenho atual do `api_search`.

Numa busca por assunto novo, o endpoint executa isto **em série, dentro do
request HTTP**, antes de devolver qualquer coisa:

| Etapa | Chamadas | Custo observado |
|---|---|---|
| SBERT da query + as duas queries no Supabase | local + 2 round trips | ~0,5 s |
| Descrição lazy (`app.py:2402`) | **5 × Claude com imagem** | **20–35 s** |
| Gravação de cada descrição (`_salvar_descricao_e_embedding`) | **5 round trips** ao Supabase | ~1,5 s |
| Re-rank (`_rerank_com_claude`) | **1 × Claude** | **3–6 s** |

São **seis chamadas pagas em fila indiana**, mais cinco aberturas de conexão
com o banco. A busca só responde quando a última termina.

Quando as cinco imagens já têm descrição, o bloco inteiro é pulado e a busca cai
para ~1 s — é o comportamento que o `README.md` descreve. O problema é que,
enquanto a biblioteca não está descrita, **"assunto novo" é quase toda busca**.
Quem acabou de apontar uma pasta de 3.000 fotos paga os 40 s repetidamente, e é
justamente o momento em que está formando opinião sobre o produto.

Sintoma prático: 40 segundos sem retorno visual é tempo suficiente para o
usuário concluir que travou. Ele recarrega a página ou clica em Buscar de novo —
o que **dispara outra rodada de chamadas pagas** sem cancelar a primeira.

---

## 2. Objetivo

Levar a busca por assunto novo de **~40 s para menos de 8 s**, sem perder
qualidade de resultado e sem aumentar o custo por busca.

A meta é dividida em etapas independentes, aplicáveis e mensuráveis uma a uma.
Cada uma pode ser mergeada sozinha.

| Etapa | O que faz | Ganho estimado | Risco |
|---|---|---|---|
| 0 | Instrumentar o tempo por fase | nenhum (mede) | nenhum |
| 1 | Paralelizar as 5 descrições | 30 s → ~7 s | médio |
| 2 | Modelo por perfil (`fast` ≠ `deep`) | ~40 % a mais | baixo |
| 3 | `timeout` e `max_retries` no cliente | corta a cauda longa | baixo |
| 4 | Descrição fora do request | ~7 s → ~1 s | alto |

**Etapas 0 a 3 são o alvo desta feature.** A etapa 4 é descrita aqui para
registrar a direção, mas deve virar documento próprio.

---

## 3. Comportamento atual (verificado no código)

### 3.1 O laço que custa caro

`backend/app.py:2394-2419`:

```python
if CLAUDE_OK:
    candidatas_sem_desc = [
        i for i, f in enumerate(rows)
        if f["tipo"] in _EXT_IMG and not (f["descricao_ia"] or "").strip()
        and clip_sims[i] > 0.15
    ]
    candidatas_sem_desc.sort(key=lambda idx: clip_sims[idx], reverse=True)
    for i in candidatas_sem_desc[:5]:
        f = rows[i]
        desc_nova = _descrever_imagem_on_demand(f["caminho"], f["nome"])
        if desc_nova:
            rows[i]["descricao_ia"] = desc_nova
            _salvar_descricao_e_embedding(uid, f["caminho"], desc_nova)
            if SBERT_OK and SKLEARN_OK:
                emb_nova = _gerar_embedding(_texto_para_embedding(desc_nova))
                ...
            corpus_tokens[i] = _tokenizar(...)
    if candidatas_sem_desc:
        bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])
```

Cada iteração faz, em sequência: leitura do arquivo do disco, redimensionamento
PIL, base64, chamada à API, encode SBERT, `get_db()`, `UPDATE`, `commit`,
`close()`. Cinco vezes.

### 3.2 O cliente sem limites

`backend/app.py:85-99`:

```python
_CLAUDE = _anthropic.Anthropic(api_key=_chave)
```

Sem `timeout` e sem `max_retries`. O padrão do SDK são 10 minutos de timeout e
2 novas tentativas. Os 40 s são o **caso normal**; sem teto, o caso ruim não
tem limite superior, e o fallback já escrito em `_rerank_com_claude`
(`return candidatos`) nunca é acionado por lentidão.

### 3.3 O modelo é o mesmo para tudo

`backend/app.py:79`:

```python
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-opus-5"
```

O mesmo modelo descreve imagem em modo `fast`, descreve em modo `deep` e julga
relevância no re-rank. O perfil `deep`/`fast` altera `max_tokens` e `effort`
(`app.py:6790-6796`), mas **não o modelo**.

### 3.4 Um detalhe que não é bug hoje, mas vira um

`if candidatas_sem_desc:` (linha 2418) recalcula o BM25 do corpus inteiro mesmo
quando **nenhuma** descrição foi obtida — basta ter havido candidatas. Se a API
estiver fora, paga-se o recálculo à toa. A condição correta é "alguma descrição
chegou".

---

## 4. Etapa 0 — Instrumentação (fazer primeiro)

Hoje o endpoint devolve só o `tempo` total. Sem separar as fases, qualquer
otimização é chute e não há como provar o ganho depois.

Deve ser adicionado um acumulador simples dentro do `api_search`:

```python
fases = {}
_t = time.time(); ...; fases["sql"] = round(time.time() - _t, 3)
```

Fases a medir: `sql`, `clip`, `descricao` (com `descricao_n` = quantas imagens
foram descritas), `persistencia`, `rerank`.

O dicionário deve sair em duas vias:

- No log do servidor, sempre: `[Busca] 38.4s — sql 0.4 | descricao 31.2 (5) | persistencia 1.6 | rerank 4.8`
- No JSON da resposta, **apenas** sob `/api/debug/scores` ou atrás de uma flag —
  nunca no payload normal de `/api/search`, que é contrato público
  (`docs/API.md`) e não deve mudar de forma por causa de diagnóstico.

**Critério de aceite:** rodando uma busca por assunto novo, o log mostra a
soma das fases batendo com o total dentro de 0,3 s.

---

## 5. Etapa 1 — Paralelizar as descrições

### 5.1 A decisão central: o que entra na thread

As cinco descrições são independentes entre si — nenhuma usa o resultado da
outra. O que impede um `ThreadPoolExecutor` ingênuo em volta do laço inteiro
são duas coisas **de dentro** do laço:

**(a) O SBERT não deve ser chamado de várias threads.** `_gerar_embedding` usa
o modelo `_SBERT` global carregado por `sentence-transformers`. Encode
concorrente no mesmo objeto não é garantido pela biblioteca, e uma corrupção
aqui é silenciosa: o embedding sai errado, é gravado no banco, e a imagem passa
a ser encontrada nas buscas erradas para sempre. Não vale o risco pelos
milissegundos economizados.

**(b) `get_db()` perde a rede de segurança dentro de thread.**
`app.py:749-766` só registra a conexão em `flask.g` quando
`has_app_context()` é verdadeiro. Threads criadas pelo executor **não herdam**
o contexto de aplicação do Flask, então o registro é pulado e o
`@app.teardown_appcontext` não recolhe nada. Como
`_salvar_descricao_e_embedding` hoje chama `conn.close()` **dentro** do `try`
(`app.py:6866-6873`), qualquer exceção entre o `get_db()` e o `close()` vaza
uma conexão — e no request normal o teardown recolhia. Em thread, não recolhe:
algumas dezenas de erros esgotam o pool e derrubam o servidor.

**Portanto, a regra desta etapa:** as threads fazem **apenas a chamada à API**
(disco, PIL, rede). SBERT, BM25 e banco voltam para a thread principal, depois
que todas as descrições chegarem.

### 5.2 Diff proposto — `api_search`

```diff
+# Teto de descrições sob demanda por busca. Elas passam a rodar em paralelo,
+# então este número é a largura do pool, e não mais o multiplicador da espera.
+TETO_DESCRICOES_POR_BUSCA = 5
+
 # ── DESCRIÇÃO SOB DEMANDA (lazy) ────────────────────────────────────────
 if CLAUDE_OK:
     candidatas_sem_desc = [
         i for i, f in enumerate(rows)
         if f["tipo"] in _EXT_IMG and not (f["descricao_ia"] or "").strip()
         and clip_sims[i] > 0.15
     ]
     candidatas_sem_desc.sort(key=lambda idx: clip_sims[idx], reverse=True)
-    for i in candidatas_sem_desc[:5]:
-        f = rows[i]
-        desc_nova = _descrever_imagem_on_demand(f["caminho"], f["nome"])
-        if desc_nova:
-            rows[i]["descricao_ia"] = desc_nova
-            _salvar_descricao_e_embedding(uid, f["caminho"], desc_nova)
-            if SBERT_OK and SKLEARN_OK:
-                emb_nova = _gerar_embedding(_texto_para_embedding(desc_nova))
-                if emb_nova is not None and query_emb is not None:
-                    import numpy as np
-                    a = np.array([emb_nova]); b = np.array([query_emb])
-                    sbert_sims[i] = max(0.0, float(cosine_similarity(a, b)[0][0]))
-            corpus_tokens[i] = _tokenizar((desc_nova or "") + " " + (f["nome"] or ""))
-    if candidatas_sem_desc:
-        bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])
+    alvos = candidatas_sem_desc[:TETO_DESCRICOES_POR_BUSCA]
+
+    # Só a chamada à API vai para as threads. SBERT e banco ficam de fora:
+    # ver a seção 5.1 do documento desta feature.
+    descritas: dict[int, str] = {}
+    if alvos:
+        from concurrent.futures import ThreadPoolExecutor, as_completed
+        with ThreadPoolExecutor(max_workers=len(alvos)) as pool:
+            futuros = {
+                pool.submit(_descrever_imagem_on_demand,
+                            rows[i]["caminho"], rows[i]["nome"]): i
+                for i in alvos
+            }
+            for fut in as_completed(futuros):
+                i = futuros[fut]
+                try:
+                    desc_nova = fut.result()
+                except Exception as exc:
+                    # Uma imagem que falha não derruba as outras quatro.
+                    print(f"[Lazy] Falhou para '{rows[i]['nome']}': {exc}")
+                    continue
+                if desc_nova:
+                    descritas[i] = desc_nova
+
+    # De volta à thread principal: embeddings, corpus e banco.
+    for i, desc_nova in descritas.items():
+        rows[i]["descricao_ia"] = desc_nova
+        if SBERT_OK and SKLEARN_OK:
+            emb_nova = _gerar_embedding(_texto_para_embedding(desc_nova))
+            if emb_nova is not None and query_emb is not None:
+                import numpy as np
+                a = np.array([emb_nova]); b = np.array([query_emb])
+                sbert_sims[i] = max(0.0, float(cosine_similarity(a, b)[0][0]))
+        corpus_tokens[i] = _tokenizar(desc_nova + " " + (rows[i]["nome"] or ""))
+
+    if descritas:
+        _salvar_descricoes_em_lote(
+            uid, [(rows[i]["caminho"], d) for i, d in descritas.items()]
+        )
+        # BM25 depende do corpus inteiro — recalcula só se algo mudou nele.
+        bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])
```

### 5.3 Diff proposto — gravação em lote

`_salvar_descricao_e_embedding` abre uma conexão por imagem. Cinco conexões e
cinco `commit` contra um Postgres na nuvem custam mais que a soma dos
`UPDATE`s. A função nova faz tudo numa conexão só, com um `commit` no fim:

```diff
+def _salvar_descricoes_em_lote(uid: int, itens: list[tuple[str, str]]) -> None:
+    """Grava várias descrições geradas sob demanda numa conexão só.
+
+    A versão por-arquivo (_salvar_descricao_e_embedding) abria uma conexão e
+    dava um commit para cada imagem. Com o Postgres na nuvem, cinco idas e
+    voltas custam mais que os próprios UPDATEs. `itens` é uma lista de
+    (caminho, descricao).
+
+    O embedding é gerado AQUI, na thread principal — nunca dentro do pool de
+    descrição, porque o modelo SBERT é global e compartilhado.
+    """
+    if not itens:
+        return
+    preparados = []
+    for caminho, desc in itens:
+        emb_vec = None
+        if SBERT_OK and desc:
+            emb_vec = _gerar_embedding(_texto_para_embedding(desc)) or None
+        preparados.append((desc, emb_vec, uid, caminho))
+
+    conn = None
+    try:
+        conn = get_db()
+        for params in preparados:
+            conn.execute(
+                "UPDATE files SET descricao_ia = %s, embedding = %s "
+                "WHERE user_id = %s AND caminho = %s",
+                params,
+            )
+        conn.commit()
+    except Exception as exc:
+        print(f"[Lazy] Falha ao salvar descrições em lote: {exc}")
+        if conn is not None:
+            try:
+                conn.rollback()
+            except Exception:
+                pass
+    finally:
+        # close() no finally: a conexão volta ao pool mesmo com exceção.
+        if conn is not None:
+            conn.close()
```

`_salvar_descricao_e_embedding` **não deve ser removida** — o
`_process_worker` pode continuar usando a versão unitária. Mas o `close()` dela
deve migrar para um `finally`, pela mesma razão.

### 5.4 Nota de duplicação

Repare que o diff da seção 5.2 calcula o embedding SBERT **e**
`_salvar_descricoes_em_lote` calcula de novo. Na implementação, escolha um
lugar: o mais limpo é a função de lote devolver
`dict[caminho, embedding]` e o laço da 5.2 reusar. Deixei os dois explícitos no
diff para cada bloco ser legível isolado — não copie os dois como estão.

### 5.5 Por que o teto continua em 5

Paralelizar não é motivo para aumentar o número. O teto existe por **custo**,
não por tempo: cada descrição é uma chamada paga. Com o laço em série, 5 era um
compromisso entre precisão e espera; agora que a espera não cresce com o
número, a única trava que resta é financeira — e ela recomenda manter 5 até
existir o controle de gasto que ainda não há em lugar nenhum do projeto.

---

## 6. Etapa 2 — Modelo por perfil

Descrever uma foto preenchendo nove campos fixos e julgar `true/false` por item
são tarefas diferentes de descrever uma imagem em modo `deep`. Hoje as três
usam `claude-opus-5`.

```diff
-CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-opus-5"
+# Modelo por tarefa. O `deep` existe para quem quer minúcia e aceita esperar;
+# o `fast` e o re-rank são o caminho quente da busca e não justificam o topo
+# da linha. Todos continuam sobrescrevíveis pelo .env, sem mexer no código.
+CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5"
+CLAUDE_MODEL_DEEP = os.environ.get("CLAUDE_MODEL_DEEP", "").strip() or "claude-opus-5"
+CLAUDE_MODEL_RERANK = os.environ.get("CLAUDE_MODEL_RERANK", "").strip() or "claude-haiku-4-5-20251001"
```

Em `_analyze_image_claude`, o modelo passa a sair do perfil:

```diff
         if perfil == "deep":
             prompt_final = prompt + (...)
             max_tok, esforco = 3000, "medium"
+            modelo = CLAUDE_MODEL_DEEP
         else:
             prompt_final = prompt
             max_tok, esforco = 2000, "low"
+            modelo = CLAUDE_MODEL
 
         resp = _CLAUDE.messages.create(
-            model=CLAUDE_MODEL,
+            model=modelo,
```

E em `_rerank_com_claude`:

```diff
         resp = _CLAUDE.messages.create(
-            model=CLAUDE_MODEL,
+            model=CLAUDE_MODEL_RERANK,
```

**Esta etapa não pode ser mergeada sem medição de qualidade.** Ver a seção 9.

O `backend/.env.example` deve documentar as três variáveis. O comentário atual
(`# Opcional: troca o modelo usado na visão e no re-rank. Padrão: claude-opus-5.`)
fica incorreto e precisa ser reescrito.

---

## 7. Etapa 3 — Teto de espera

```diff
-        _CLAUDE = _anthropic.Anthropic(api_key=_chave)
+        # timeout: o re-rank está no caminho do request. Sem teto, uma chamada
+        # lenta prende a busca e o fallback de _rerank_com_claude
+        # (return candidatos) nunca chega a rodar.
+        #
+        # max_retries=1: o padrão do SDK é 2, e com retry automático um timeout
+        # de 20s vira 60s de espera real. Aqui é melhor degradar rápido — o
+        # motor tem resultado para mostrar sem a IA.
+        _CLAUDE = _anthropic.Anthropic(
+            api_key=_chave,
+            timeout=float(os.environ.get("CLAUDE_TIMEOUT", "20")),
+            max_retries=1,
+        )
```

20 s como padrão, não 10: a descrição em modo `deep` com `effort: "medium"` é
legitimamente lenta, e cortá-la cedo demais transformaria uma feature em erro.
Quem quiser mais agressividade ajusta pelo `.env`.

---

## 8. Etapa 4 — Tirar a descrição do request (direção futura)

Registro da direção. **Não implementar nesta feature.**

As etapas 1 a 3 reduzem a espera; não a eliminam, porque a busca continua
esperando a IA. A correção definitiva é a busca **responder na hora** com o que
já sabe e completar depois.

Isso é viável porque o motor já pontua imagem sem descrição: o
`blended = min(0.70, 0.85 * s_visual)` (`app.py:2462`) existe exatamente para o
caso "só tenho CLIP". Um resultado sem descrição já aparece hoje — só aparece
depois de 40 s de espera por descrições que nem são dele.

Desenho sugerido:

1. `/api/search` responde imediatamente, sem descrever nada, e devolve os ids
   das candidatas que entraram na fila de descrição.
2. As descrições vão para o `_queue` do `_process_worker`, que já existe.
3. O front acompanha e atualiza os cards conforme as descrições chegam — o
   padrão já está implementado no commit `feat(home): a galeria acompanha a
   análise, sem precisar de F5`.

Ganho: busca em ~1 s **sempre**, e a precisão melhora sozinha em vez de cobrar
a espera adiantada. Custo: mexe no contrato da API e no front, por isso merece
documento próprio.

---

## 9. Riscos e regressões a verificar

| Risco | Onde | Como verificar |
|---|---|---|
| Conexão vazando em thread | `_salvar_descricoes_em_lote` | Rodar 50 buscas seguidas com a API derrubada; o pool não pode esgotar |
| SBERT chamado concorrente | laço da 5.2 | Revisão: nenhum `_gerar_embedding` dentro do `ThreadPoolExecutor` |
| Ordem de resultado mudou | `as_completed` não preserva ordem | Os índices vêm do dict `futuros`, não da ordem de chegada — cobrir com teste |
| Qualidade caiu com modelo menor | etapa 2 | Ver abaixo |
| Custo subiu sem querer | etapa 1 | O teto continua 5; conferir no log que `descricao_n <= 5` |

**Sobre a etapa 2 — medição obrigatória.** Antes de mergear a troca de modelo,
monte um conjunto de ~30 buscas com o resultado esperado anotado à mão e rode as
duas versões. O que precisa ser comparado não é "a descrição ficou boa", e sim:
os mesmos arquivos aparecem, na mesma faixa de posição? Descrição pior degrada a
busca de forma indireta e difícil de notar em teste manual solto — ela vira
embedding, e o erro fica gravado no banco.

Se não houver conjunto de avaliação, **a etapa 2 não deve ser mergeada**, mesmo
funcionando. As etapas 0, 1 e 3 não têm essa dependência: nenhuma delas muda o
que a IA responde.

---

## 10. Testes

Os testes da suíte substituem a API e os modelos antes de importar o backend
(`tests/conftest.py`), então tudo aqui é testável sem chave e sem banco.

**Novo arquivo: `tests/unit/test_descricao_paralela.py`**

| Teste | O que garante |
|---|---|
| Cinco candidatas geram cinco chamadas | O teto não foi perdido no refactor |
| Uma candidata que levanta exceção não derruba as outras | O `try` dentro do `as_completed` |
| Descrição chegando fora de ordem é atribuída ao índice certo | O ponto mais provável de bug |
| Nenhuma descrição obtida → BM25 **não** é recalculado | Corrige o `if candidatas_sem_desc` da seção 3.4 |
| Falha no lote não deixa conexão aberta | O `finally` da 5.3 |
| Zero candidatas → nenhuma thread criada | Busca com cache quente não paga overhead |

**Ajuste em `tests/unit/test_carga_dos_modelos.py`:** o cliente agora nasce com
`timeout` e `max_retries` — se houver asserção sobre a construção do cliente,
ela muda.

**Carga (`tests/load/locustfile.py`):** a tarefa de busca contra o mock não
exercita esse caminho, porque o mock não chama IA. O valor aqui é o p95 do
`SEARCHPLUS_LOAD_MAX_P95_IA_MS`, hoje em 5000 ms — com a etapa 1 esse limite
deve passar a ser cumprido em vez de tolerado.

---

## 11. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `backend/app.py` | Etapas 0 a 3 — todas as mudanças de código |
| `backend/.env.example` | `CLAUDE_MODEL_DEEP`, `CLAUDE_MODEL_RERANK`, `CLAUDE_TIMEOUT`; corrigir o comentário do `CLAUDE_MODEL` |
| `tests/unit/test_descricao_paralela.py` | Novo |
| `docs/10-requisitos-nao-funcionais.md` | O requisito de tempo de busca precisa refletir a meta nova |
| `README.md` | A frase "a primeira busca por um assunto novo demora alguns segundos" fica desatualizada |

**Não muda:** `mock_server.py` (não chama IA, então o contrato dele já está
correto), `docs/API.md` (o payload de `/api/search` é o mesmo), `schema.sql`,
`index.html`, `script.js`, `style.css`.

Esse último ponto é o que torna a feature segura de mergear: **nada do que o
front recebe muda de forma.** Só chega antes.

---

## 12. Ordem de execução sugerida

1. Etapa 0 — instrumentar e **registrar os números de antes** num comentário do PR
2. Etapa 3 — `timeout`, é isolada e de risco baixo
3. Etapa 1 — paralelização, com os testes da seção 10
4. Medir de novo e comparar com o número do passo 1
5. Etapa 2 — só depois do conjunto de avaliação existir

Os passos 1 a 4 já devem entregar a maior parte da meta. Se a medição do passo 4
mostrar que o re-rank virou a fase dominante, a etapa 2 deixa de ser opcional.
