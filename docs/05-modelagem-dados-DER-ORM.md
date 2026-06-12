# Modelagem de Dados — Search+ (DER + ORM)

> **Abordagem da equipe: SQL (Relacional).**
> Banco de dados: **PostgreSQL hospedado no Supabase**, com a extensão **pgvector**
> para busca por similaridade vetorial. O acesso é feito via **psycopg2**
> (driver oficial do PostgreSQL para Python).

As trilhas **NoSQL (Mongoose)** e **Sem Banco (LocalStorage)** do enunciado
**não se aplicam** a este projeto, pois a equipe adotou a abordagem SQL.

---

## 1. Diagrama Entidade-Relacionamento (DER)

O DER em PlantUML está em [`04-der.puml`](04-der.puml). Resumo das entidades:

| Entidade | Papel |
|---|---|
| **users** | Usuários do sistema (login, senha hasheada, config visual em JSONB) |
| **folders** | Pastas do computador que o usuário pede para a IA monitorar |
| **files** | Arquivos indexados, com a descrição da IA e os vetores de busca |
| **collections** | Coleções (playlists) criadas pelo usuário |
| **collection_files** | Tabela associativa N:N entre `collections` e `files` |

### Relacionamentos
- `users 1—N folders` (ON DELETE CASCADE)
- `users 1—N files` (ON DELETE CASCADE)
- `users 1—N collections` (ON DELETE CASCADE)
- `folders 1—N files` (ON DELETE SET NULL — apagar a pasta não apaga o arquivo)
- `collections N—N files` (via `collection_files`)

O DDL completo e versionado está em [`../backend/schema.sql`](../backend/schema.sql),
e é aplicado automaticamente pelo backend na primeira execução (`init_db()`).

---

## 2. Camada ORM / Acesso a Dados

O projeto **não usa um ORM tradicional** (SQLAlchemy/Django ORM). O acesso é feito
com **SQL parametrizado via psycopg2**, encapsulado numa camada de abstração própria
que cumpre o papel de mapeamento objeto-relacional de forma leve:

### Pool de conexões + wrapper (`backend/app.py`)
```python
_pg_pool = pg_pool.ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)

class _PooledConnection:
    """Devolve a conexão ao pool no .close() em vez de fechá-la.
       Mantém a interface (execute/commit/close) e registra o adapter
       pgvector para mapear list[float] <-> vector(N) automaticamente."""
    def __init__(self, raw):
        register_vector(raw)
        self._cursor = raw.cursor(cursor_factory=RealDictCursor)
```

**Por que essa escolha (justificativa técnica):**
1. **pgvector** — a busca semântica precisa do tipo nativo `vector(384)`/`vector(512)`
   e do operador de distância `<=>`, que um ORM genérico não expõe bem. SQL direto
   dá controle total sobre `ORDER BY embedding <=> %s` com índice HNSW.
2. **RealDictCursor** — cada linha já volta como dicionário (`row["nome"]`),
   funcionando como um mapeamento objeto-relacional simples.
3. **Segurança** — todas as queries usam parâmetros `%s` (anti-SQL-injection).

### Mapeamento conceitual (entidade → acesso)
| Entidade | Operações implementadas | Endpoint |
|---|---|---|
| users | create, read, auth | `/api/register`, `/api/login`, `/api/config` |
| folders | CRUD | `/api/folders`, `/api/folders/<id>` |
| files | read, update (indexação), busca vetorial | `/api/search`, `/api/search_by_image` |
| collections | CRUD | `/api/collections`, `/api/collections/<id>` |
| collection_files | add, remove | `/api/collections/<id>/files` |

> Caso a disciplina exija um ORM "nominal", o mapeamento acima pode ser portado
> para SQLAlchemy declarando uma classe por tabela — mas a equipe optou pelo
> acesso direto pelos motivos de pgvector acima.

---

## 3. Por que Supabase (PostgreSQL)
- **Gratuito** e na nuvem — os dados ficam acessíveis de qualquer máquina.
- **pgvector nativo** — essencial para a busca semântica por embeddings.
- **JSONB** — guarda a configuração visual do usuário (tema, cores) de forma flexível.
- **Migração documentada**: o projeto começou em SQLite e migrou para Supabase
  (commit `aff9614`), provando a evolução da arquitetura ao longo das sprints.
