-- Schema do Search+ no Supabase Postgres
-- Roda esse arquivo uma vez via psycopg2 (ou cola no SQL Editor do Supabase)

-- Extensão pgvector — embeddings nativos com busca por similaridade
CREATE EXTENSION IF NOT EXISTS vector;

-- Usuários
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    config_json   JSONB DEFAULT '{}'::jsonb
);

-- Pastas monitoradas
CREATE TABLE IF NOT EXISTS folders (
    id                    SERIAL PRIMARY KEY,
    user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path                  TEXT NOT NULL,
    name                  TEXT NOT NULL,
    added_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prioridades           JSONB DEFAULT '["tudo"]'::jsonb,
    perfil_analise        TEXT DEFAULT 'fast',
    janela_processamento  TEXT DEFAULT 'always',
    UNIQUE (user_id, path)
);

-- Arquivos indexados (com embeddings nativos)
-- SBERT MiniLM-L12 multilingual = 384 dimensões
-- CLIP ViT-B-32 multilingual    = 512 dimensões
CREATE TABLE IF NOT EXISTS files (
    id              SERIAL PRIMARY KEY,
    folder_id       INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nome            TEXT NOT NULL,
    caminho         TEXT NOT NULL,
    tipo            TEXT NOT NULL,
    descricao_ia    TEXT DEFAULT '',
    embedding       vector(384),
    embedding_clip  vector(512),
    data_adicionado TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    favorito        INTEGER DEFAULT 0,
    processado      INTEGER DEFAULT 0,
    UNIQUE (user_id, caminho)
);

-- Assinatura do arquivo no disco, para o "verificar alterações".
-- mtime + tamanho é o par mais barato que distingue um arquivo editado de um
-- intocado: não precisa abrir nem ler o conteúdo. Hash seria mais exato, mas
-- custaria ler byte a byte de toda a pasta a cada verificação.
--
-- Ficam NULL nos arquivos indexados antes desta coluna existir. NULL aqui
-- significa "nunca soube como era", e não "não mudou" — a verificação grava a
-- assinatura desses sem acusar alteração, porque não há com o que comparar.
ALTER TABLE files ADD COLUMN IF NOT EXISTS mtime   DOUBLE PRECISION;
ALTER TABLE files ADD COLUMN IF NOT EXISTS tamanho BIGINT;

-- Arquivo que sumiu do disco: fica marcado, não é apagado. O registro guarda
-- descrição, embeddings e as coleções de que participa; apagar por causa de um
-- HD externo desconectado jogaria fora trabalho de IA que não volta sozinho.
-- Volta a NULL sozinho quando o arquivo reaparece.
ALTER TABLE files ADD COLUMN IF NOT EXISTS ausente_em TIMESTAMPTZ;

-- Índices: HNSW pra busca rápida por similaridade (pgvector >= 0.5)
-- cosine_ops corresponde ao operador <=> (cosine distance)
CREATE INDEX IF NOT EXISTS files_embedding_idx
    ON files USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS files_embedding_clip_idx
    ON files USING hnsw (embedding_clip vector_cosine_ops);

-- Índices auxiliares pra queries comuns
CREATE INDEX IF NOT EXISTS files_user_processado_idx ON files (user_id, processado);
CREATE INDEX IF NOT EXISTS folders_user_idx ON folders (user_id);

-- Coleções (playlists de arquivos)
CREATE TABLE IF NOT EXISTS collections (
    id        SERIAL PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nome      TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, nome)
);

-- Vínculo opcional entre uma coleção e uma pasta do computador.
-- Quando preenchido, a coleção deixa de ser só um agrupamento interno e passa
-- a ter um espelho no disco. `modo_sync` decide o que acontece quando novas
-- imagens entram na coleção:
--   'auto'      → copia para a pasta na hora, sem perguntar
--   'perguntar' → pergunta a cada adição
--   'manual'    → nunca copia sozinho; só pelo botão Exportar
-- Coleção sem pasta vinculada fica em 'manual' e se comporta como antes.
ALTER TABLE collections ADD COLUMN IF NOT EXISTS pasta_vinculada TEXT;
ALTER TABLE collections ADD COLUMN IF NOT EXISTS modo_sync TEXT NOT NULL DEFAULT 'manual';

-- Histórico de TODAS as pastas que o app gerou para uma coleção.
-- Exportar duas vezes cria "Natureza" e "Natureza (1)": as duas ficam aqui.
-- `collections.pasta_vinculada` aponta para a que recebe novas imagens; esta
-- tabela é o conjunto completo, usado ao excluir a coleção para o usuário
-- escolher, pasta a pasta, o que apagar do disco e o que preservar.
-- É também a lista de caminhos que /api/open_folder aceita abrir.
CREATE TABLE IF NOT EXISTS collection_folders (
    id            SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    caminho       TEXT NOT NULL,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, caminho)
);

CREATE INDEX IF NOT EXISTS collection_folders_col_idx ON collection_folders (collection_id);
CREATE INDEX IF NOT EXISTS collection_folders_user_idx ON collection_folders (user_id);

-- Quais pastas recebem as novas imagens da coleção. É um CONJUNTO: podem ser
-- várias (organizar em duas pastas), uma, ou nenhuma (parar de enviar sem
-- perder o registro das pastas já criadas).
-- Esta coluna é a fonte da verdade sobre o DESTINO; `collections.modo_sync`
-- continua respondendo QUANDO enviar.
ALTER TABLE collection_folders ADD COLUMN IF NOT EXISTS recebe BOOLEAN NOT NULL DEFAULT FALSE;

-- Migração das coleções que já usavam o destino único: a pasta apontada por
-- `collections.pasta_vinculada` passa a ser a primeira do conjunto. Roda uma
-- vez; depois disso nenhuma linha casa e o UPDATE é inócuo.
UPDATE collection_folders cf
   SET recebe = TRUE
  FROM collections c
 WHERE cf.collection_id = c.id
   AND c.pasta_vinculada IS NOT NULL
   AND cf.caminho = c.pasta_vinculada
   AND cf.recebe = FALSE
   AND NOT EXISTS (
       SELECT 1 FROM collection_folders x
        WHERE x.collection_id = cf.collection_id AND x.recebe = TRUE
   );

-- Relação N:N entre coleções e arquivos
-- Lixeira: o que foi excluído e ainda dá para trazer de volta.
--
-- Guarda um RETRATO do que foi apagado, não uma marca de "apagado" na linha
-- original. A alternativa seria uma coluna `excluido_em` em collections e
-- collection_files, mas aí cada uma das ~22 consultas que leem coleção teria
-- de ganhar `AND excluido_em IS NULL`. Esquecer uma só não quebra nada de
-- forma visível: ela simplesmente passa a enxergar coleção excluída, e o
-- usuário consegue, por exemplo, adicionar uma foto a uma coleção que está
-- na lixeira. Com o retrato, a linha some de verdade e nenhuma consulta
-- precisa saber que a lixeira existe.
--
-- `conteudo` guarda o suficiente para reconstruir: a coleção com o MESMO id
-- (para que qualquer coisa que aponte para ele continue apontando), os
-- arquivos que ela tinha e as pastas geradas.
CREATE TABLE IF NOT EXISTS lixeira (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tipo        TEXT NOT NULL,
    rotulo      TEXT NOT NULL,
    conteudo    JSONB NOT NULL,
    excluido_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS lixeira_user_idx ON lixeira (user_id, excluido_em DESC);

CREATE TABLE IF NOT EXISTS collection_files (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    adicionado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (collection_id, file_id)
);

CREATE INDEX IF NOT EXISTS collections_user_idx ON collections (user_id);
CREATE INDEX IF NOT EXISTS collection_files_col_idx ON collection_files (collection_id);
