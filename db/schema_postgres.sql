CREATE TABLE IF NOT EXISTS documents (
  id SERIAL PRIMARY KEY,
  file_name TEXT UNIQUE,
  short_title TEXT,
  doc_number TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS articles (
  id SERIAL PRIMARY KEY,
  document_id INT REFERENCES documents(id) ON DELETE CASCADE,
  number TEXT,
  text   TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  id SERIAL PRIMARY KEY,
  document_id INT REFERENCES documents(id) ON DELETE CASCADE,
  type TEXT,
  text TEXT,
  normalized TEXT,
  global_id TEXT
);

CREATE TABLE IF NOT EXISTS relations (
  id SERIAL PRIMARY KEY,
  document_id INT REFERENCES documents(id) ON DELETE CASCADE,
  source_id INT,
  target_id INT,
  type TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_docnum      ON documents(doc_number);
CREATE INDEX IF NOT EXISTS idx_article_doc_num ON articles(document_id, number);
CREATE INDEX IF NOT EXISTS idx_entity_norm     ON entities(normalized, type);
CREATE INDEX IF NOT EXISTS idx_entity_doc      ON entities(document_id);
