-- Incidents group many raw alerts. Agent output (root cause, evidence, proposed action, reasoning
-- trace, token/cost usage) is stored as JSONB: the schema of agent output evolves faster than the
-- relational core, and the alert service treats it as an opaque document it only displays.
CREATE TABLE incidents (
    id                UUID PRIMARY KEY,
    title             VARCHAR(300) NOT NULL,
    status            VARCHAR(32)  NOT NULL,
    severity          VARCHAR(16)  NOT NULL,
    affected_services JSONB        NOT NULL DEFAULT '[]'::jsonb,
    summary           TEXT,
    root_cause        JSONB,
    proposed_action   JSONB,
    reasoning_trace   JSONB,
    llm_usage         JSONB,
    execution         JSONB,
    first_alert_at    TIMESTAMPTZ  NOT NULL,
    summarized_at     TIMESTAMPTZ,
    notified_at       TIMESTAMPTZ,
    decided_at        TIMESTAMPTZ,
    decided_by        VARCHAR(120),
    decision_comment  TEXT,
    created_at        TIMESTAMPTZ  NOT NULL,
    updated_at        TIMESTAMPTZ  NOT NULL,
    version           BIGINT       NOT NULL DEFAULT 0
);

CREATE INDEX idx_incidents_status ON incidents (status);
CREATE INDEX idx_incidents_created_at ON incidents (created_at DESC);

CREATE TABLE alerts (
    id              UUID PRIMARY KEY,
    fingerprint     VARCHAR(64)  NOT NULL,
    source          VARCHAR(64)  NOT NULL,
    service         VARCHAR(120) NOT NULL,
    severity        VARCHAR(16)  NOT NULL,
    message         TEXT         NOT NULL,
    alert_timestamp TIMESTAMPTZ  NOT NULL,
    received_at     TIMESTAMPTZ  NOT NULL,
    labels          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    incident_id     UUID REFERENCES incidents (id)
);

CREATE INDEX idx_alerts_incident_id ON alerts (incident_id);
CREATE INDEX idx_alerts_timestamp ON alerts (alert_timestamp DESC);
CREATE INDEX idx_alerts_fingerprint ON alerts (fingerprint);
