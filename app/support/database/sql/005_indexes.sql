-- No vector index: an exact scan is fast at this size and stays correct with filters.
CREATE INDEX IF NOT EXISTS incidents_search_vector_idx ON incidents USING gin (search_vector);
CREATE INDEX IF NOT EXISTS incidents_filters_idx
    ON incidents (environment_id, service_id, severity_id);
CREATE INDEX IF NOT EXISTS incidents_created_at_idx ON incidents (created_at);
CREATE INDEX IF NOT EXISTS incident_tags_tag_idx ON incident_tags (tag_id, incident_id);
