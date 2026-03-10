CREATE TABLE IF NOT EXISTS sensor_data (
    id SERIAL PRIMARY KEY,
    dev_eui VARCHAR(16) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    temperature REAL,
    humidity REAL,
    rssi REAL,
    snr REAL
);
