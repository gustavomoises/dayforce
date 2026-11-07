CREATE TABLE IF NOT EXISTS environment_types (
    id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS severity_types (
    id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    rank smallint NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS service_types (
    id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL
);
