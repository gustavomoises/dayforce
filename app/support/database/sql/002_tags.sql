CREATE TABLE IF NOT EXISTS tags (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE CHECK (name = lower(name))
);
