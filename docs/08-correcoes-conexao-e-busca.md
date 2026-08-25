# Correções — conexão Postgres e busca visual (CLIP)

**Data:** 13/08/2026
**Arquivos alterados:** `backend/.env`, `backend/.env.example`, `backend/app.py`

Duas falhas independentes, ambas na camada nova de Postgres/pgvector (a migração
saindo do SQLite). A primeira impedia o app de subir; a segunda deixava a busca
retornando vazio.

---

## Bug 1 — App não sobe: `could not translate host name`

### Sintoma

```
psycopg2.OperationalError: could not translate host name
"db.pexxuyifyujvmshqtpuo.supabase.co" to address: Name or service not known
```

Estouro em `backend/app.py:343`, na criação do `ThreadedConnectionPool`.

### Causa

O host de **conexão direta** do Supabase (`db.<ref>.supabase.co`) só publica
registro DNS **AAAA (IPv6)** — não tem registro A (IPv4). O Supabase removeu o
IPv4 da conexão direta; ele agora é recurso pago (add-on de IPv4 dedicado).

Diagnóstico que confirma:

```
A/IPv4    → ERRO: No address associated with hostname
AAAA/IPv6 → 2600:1f1e:90b:a701:bb8d:9387:5931:5d6a
```

Em máquina/rede sem IPv6 utilizável o `getaddrinfo()` falha, e o psycopg2
reporta como "nome não encontrado" — mensagem enganosa, porque parece projeto
inexistente ou fora do ar. O projeto estava normal.

### Correção

Migrado para o **pooler (Supavisor)**, que atende em IPv4. A região foi
identificada por handshake do protocolo Postgres contra cada endpoint —
`aws-1-sa-east-1` respondeu com pedido de autenticação (tenant existe);
todos os outros responderam `ENOTFOUND tenant/user not found`.

`backend/.env:12`

```diff
- DATABASE_URL=postgresql://postgres:<SENHA>@db.pexxuyifyujvmshqtpuo.supabase.co:5432/postgres
+ DATABASE_URL=postgresql://postgres.pexxuyifyujvmshqtpuo:<SENHA>@aws-1-sa-east-1.pooler.supabase.com:5432/postgres
```

Três mudanças, todas obrigatórias no pooler:

| Item    | Direto                        | Pooler                                  |
| ------- | ----------------------------- | --------------------------------------- |
| host    | `db.<ref>.supabase.co`        | `aws-1-sa-east-1.pooler.supabase.com`   |
| usuário | `postgres`                    | `postgres.<project-ref>`                |
| porta   | `5432`                        | `5432` session · `6543` transaction     |

Ficou em **session mode (5432)**: comporta-se como Postgres normal e é seguro
com o `ThreadedConnectionPool(1, 10)` que a app já mantém do lado do cliente.
Transaction mode (6543) escalaria melhor, mas não suporta prepared statements
de sessão — se for migrar, validar antes.

`backend/.env.example` também foi atualizado com o formato do pooler e um
comentário explicando o porquê, para não repetir o erro em outra máquina.

### Validação

```
CONEXAO OK
extensoes: pg_stat_statements, pgcrypto, plpgsql, supabase_vault, uuid-ossp, vector
tabelas:   collection_files(1) collections(1) files(27) folders(4) users(4)
```

---

## Bug 2 — Busca não retorna resultados

### Sintoma

Login, galeria e navegação funcionando; qualquer pesquisa volta vazia ou com
pouquíssimos itens.

### Causa

**`pgvector` 0.5.0 devolve colunas `vector` como objeto `Vector`** — que não é
iterável nem convertível para float. O código tratava o retorno como se fosse
`numpy.ndarray`.

Em `/api/search`:

```python
img_vec = np.array([f["embedding_clip"]])            # → ndarray dtype=object
clip_sims[i] = float(cosine_similarity(...)[0][0])   # → TypeError
except Exception:
    pass                                             # ← erro engolido
```

```
TypeError: float() argument must be a string or a real number, not 'Vector'
```

O `except ... pass` mascarava a exceção e deixava `clip_sims[i] = 0.0` para
**toda** imagem, em **toda** busca. Nada aparecia no log.

#### Efeito cascata

O acervo do usuário de teste (`kevin`, uid 28) tem 12 arquivos, dos quais **9
são imagens sem descrição**, indexadas apenas com embedding CLIP:

| user_id | total | proc=1 | c/ SBERT | c/ CLIP | sem descrição |
| ------- | ----- | ------ | -------- | ------- | ------------- |
| 28      | 12    | 12     | 3        | 9       | 9             |

Com `clip_sim = 0`, essas 9 imagens falhavam nas quatro condições do filtro de
`_filtrar_e_pontuar()` — `tem_texto` (sem SBERT), `tem_visual` (CLIP zerado),
`tem_keyword` (sem descrição) e `match_literal` (descrição vazia) — e eram
descartadas em toda busca.

Pior: o fluxo de **descrição sob demanda** exige `clip_sims[i] > 0.15` para
acionar o Claude. Com o CLIP quebrado, as imagens nunca ganhavam descrição, e
sem descrição nunca voltariam a pontuar por texto. O bug se auto-perpetuava.

Sobravam só os 3 arquivos com SBERT — daí a impressão de "busca vazia".

### Correção

**1. Helper novo** — `backend/app.py:400`, logo após `get_db()`:

```python
def _vec_to_list(v):
    """
    Normaliza um vetor lido do banco para lista de float puro.
    pgvector >= 0.4 devolve um objeto `Vector`, que NÃO é iterável...
    """
    if v is None:
        return None
    to_list = getattr(v, "to_list", None)     # pgvector.Vector
    if callable(to_list):
        return [float(x) for x in to_list()]
    tolist = getattr(v, "tolist", None)       # numpy.ndarray
    if callable(tolist):
        return [float(x) for x in tolist()]
    if isinstance(v, str):                    # fallback: '[0.1,0.2,...]'
        return [float(x) for x in v.strip("[]").split(",") if x.strip()]
    return [float(x) for x in v]              # list/tuple
```

Aceita `Vector`, ndarray, string e list para não voltar a quebrar em upgrade ou
downgrade do pgvector, nem quando o `register_vector()` falha (o wrapper
`_PooledConnection` já ignora essa falha em silêncio).

**2. `/api/search`** — `backend/app.py:1536`:

```diff
- img_vec = np.array([f["embedding_clip"]])
+ img_vec = np.array([_vec_to_list(f["embedding_clip"])], dtype=float)
  clip_sims[i] = float(cosine_similarity(clip_q_np, img_vec)[0][0])
- except Exception:
-     pass
+ except Exception as e:
+     print(f"[CLIP] falha ao comparar '{f['nome']}': {type(e).__name__}: {e}")
```

**3. `/api/search_by_image`** — `backend/app.py:1701`. Mesmo bug em outra forma;
esta rota estava **100% quebrada** para busca a partir de arquivo já indexado:

```diff
- query_vec = [float(x) for x in row["embedding_clip"]]   # TypeError: not iterable
+ query_vec = _vec_to_list(row["embedding_clip"])
```

### Validação

Cálculo rodado contra os 9 embeddings reais do banco:

```
ANTES:  TypeError: float() argument ... not 'Vector'  → clip_sim = 0.0 (todas)

DEPOIS: 1.0000  IMG_9734.JPEG            (auto-similaridade, sanity check)
        0.7958  91c79ba5-a8de-...JPEG
        0.4772  wallpapersden...wxl.jpg
        0.4672  wallpapersden...2048x1
        0.4288  transferir.jpg
        0.3881  wallpaper.jpg
        0.3858  wallpaper2.jpg
        0.3524  IMG_9805.PNG
        0.2785  Certificado.jpg

        9/9 acima do limiar tem_visual (>0.25)
```

---

## Pendências (não alteradas)

1. **Limiar do CLIP pode estar apertado para busca textual.** Os números acima
   são similaridade **imagem↔imagem**. Consulta **texto↔imagem** no CLIP produz
   valores naturalmente mais baixos (tipicamente 0,15–0,35), e o corte é
   `tem_visual >= 0.25` (`_filtrar_e_pontuar`). Vale instrumentar com buscas
   reais antes de calibrar.

2. **Cobertura de embeddings incompleta:** 9 de 27 arquivos sem SBERT, 3 sem
   CLIP. Um "Re-analisar" resolve.

3. **`register_vector()` falha em silêncio** no `_PooledConnection.__init__`
   (`except Exception` só faz `print`). Como o `_vec_to_list` agora cobre o caso
   degradado, é aceitável — mas convém elevar a severidade do log.

4. **Rotas `/api/search_history` sem tabela correspondente.** O schema não tem
   `search_history`; o histórico aparenta viver em `users.config_json`.
   Confirmar se é intencional.

5. **Segredos versionados em texto puro.** `backend/.env` carrega
   `SUPABASE_SERVICE_ROLE_KEY` (ignora RLS, acesso total ao banco),
   `ANTHROPIC_API_KEY` e a senha do Postgres. O arquivo está no `.gitignore`,
   mas essas credenciais já circularam fora da máquina — **recomendada rotação
   das três**.
