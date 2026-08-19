-- Supabase / PostgreSQL schema for the RAG knowledge assistant.
-- Run this once in the Supabase SQL editor before the first ingest.

create extension if not exists vector;

create table if not exists document_chunks (
    chunk_id     text primary key,
    document_id  text        not null,
    chunk_index  integer     not null,
    content      text        not null,
    source       text        default '',
    title        text        default '',
    metadata     jsonb       default '{}'::jsonb,
    -- Must match EMBEDDING_DIMENSIONS. voyage-3 returns 1024.
    embedding    vector(1024),
    created_at   timestamptz default now()
);

-- Retrieval always filters by document, so this index earns its keep on re-ingest.
create index if not exists document_chunks_document_id_idx
    on document_chunks (document_id);

-- IVFFlat for approximate nearest-neighbour search.
-- `lists` is a tuning knob: roughly sqrt(row_count) is a sound starting point.
-- Build this AFTER the first bulk ingest — an index built on an empty table
-- produces poor centroids and degrades recall.
create index if not exists document_chunks_embedding_idx
    on document_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- Similarity search. `<=>` is pgvector's cosine distance, so similarity is 1 - distance.
create or replace function match_document_chunks (
    query_embedding vector(1024),
    match_count     int   default 5,
    min_similarity  float default 0.0
)
returns table (
    chunk_id    text,
    document_id text,
    chunk_index integer,
    content     text,
    source      text,
    title       text,
    metadata    jsonb,
    similarity  float
)
language sql stable
as $$
    select
        c.chunk_id,
        c.document_id,
        c.chunk_index,
        c.content,
        c.source,
        c.title,
        c.metadata,
        1 - (c.embedding <=> query_embedding) as similarity
    from document_chunks c
    where c.embedding is not null
      and 1 - (c.embedding <=> query_embedding) >= min_similarity
    order by c.embedding <=> query_embedding
    limit match_count;
$$;

-- Row Level Security: enable and add a policy matching your auth model before
-- exposing this table to client-side keys.
-- alter table document_chunks enable row level security;
