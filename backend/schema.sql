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

-- Índices: HNSW pra busca rápida por similaridade (pgvector >= 0.5)
-- cosine_ops corresponde ao operador <=> (cosine distance)
CREATE INDEX IF NOT EXISTS files_embedding_idx
    ON files USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS files_embedding_clip_idx
    ON files USING hnsw (embedding_clip vector_cosine_ops);

-- Índices auxiliares pra queries comuns
CREATE INDEX IF NOT EXISTS files_user_processado_idx ON files (user_id, processado);
CREATE INDEX IF NOT EXISTS folders_user_idx ON folders (user_id);
