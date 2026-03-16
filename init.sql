-- Detections table for LoRaWAN object detection uplinks.
-- type_code is a raw integer — decode it in your application layer.
-- node_timestamp is seconds-since-midnight UTC as reported by the node itself.
-- timestamp is the network-server reception time (from LoRaWAN metadata).

CREATE TABLE IF NOT EXISTS nodes (
    dev_eui          VARCHAR(16) PRIMARY KEY,
    name             VARCHAR(255),
    latitude         REAL NOT NULL,
    longitude        REAL NOT NULL,
    altitude         REAL DEFAULT 0,
    range            REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
    id               SERIAL PRIMARY KEY,
    dev_eui          VARCHAR(16)  NOT NULL REFERENCES nodes(dev_eui),
    timestamp        TIMESTAMPTZ  NOT NULL,   -- network server reception time
    type_code        SMALLINT     NOT NULL,   -- raw number; decode in app layer
    azimuth          REAL         NOT NULL,   -- degrees, 0.0–359.9
    node_timestamp   INTEGER,                 -- seconds since midnight UTC (node clock)
    rssi             REAL,
    snr              REAL
);

CREATE INDEX IF NOT EXISTS idx_detections_dev_eui   ON detections (dev_eui);
CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detections_type_code ON detections (type_code);
