from flask import Flask, request, jsonify, render_template
import psycopg2
from psycopg2.extras import execute_values
import os
from database import connect_to_database, close_db_connection

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    endpoints = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            methods = ', '.join(sorted([m for m in rule.methods if m not in ['OPTIONS', 'HEAD']]))
            endpoints[rule.rule] = f"Methods: {methods}"
            
    return jsonify({
        "service": "DIVS Gateway HTTP Endpoint",
        "description": "Flask API for handling Chirpstack integrations",
        "endpoints": endpoints
    }), 200

@app.route("/map", methods=["GET"])
def map_view():
    return render_template("map.html")

@app.route("/nodes", methods=["GET"])
def get_nodes():
    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute("SELECT dev_eui, name, latitude, longitude, altitude, range FROM nodes")
        rows = cursor.fetchall()
        
        nodes = []
        for row in rows:
            nodes.append({
                "dev_eui": row[0],
                "name": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "altitude": row[4],
                "range": row[5]
            })
        return jsonify(nodes), 200
    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"Error fetching nodes: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

@app.route("/nodes", methods=["POST"])
def create_node():
    data = request.get_json()
    dev_eui = data.get("dev_eui")
    name = data.get("name")
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    altitude = data.get("altitude", 0)
    node_range = data.get("range")

    if not all([dev_eui, latitude, longitude, node_range]):
         return jsonify({"status": "error", "message": "Missing required fields"}), 400

    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute(
            """
            INSERT INTO nodes (dev_eui, name, latitude, longitude, altitude, range)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (dev_eui, name, latitude, longitude, altitude, node_range)
        )
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"DB insert failed, rolled back: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok"}), 201

@app.route("/nodes/<dev_eui>", methods=["PUT"])
def update_node(dev_eui):
    data = request.get_json()
    name = data.get("name")
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    altitude = data.get("altitude", 0)
    node_range = data.get("range")

    if not all([latitude, longitude, node_range]):
         return jsonify({"status": "error", "message": "Missing required fields"}), 400

    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute(
            """
            UPDATE nodes 
            SET name=%s, latitude=%s, longitude=%s, altitude=%s, range=%s
            WHERE dev_eui=%s
            """,
            (name, latitude, longitude, altitude, node_range, dev_eui)
        )
        
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Node not found"}), 404
            
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"DB update failed, rolled back: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok"}), 200

@app.route("/uplink", methods=["POST"])
def uplink():
    # ChirpStack sends all event types (up, status, join, ack, txack, log, location)
    # to the same URL. We only care about uplink data events.
    event = request.args.get("event")
    if event != "up":
        return jsonify({"status": "ignored", "event": event}), 200

    data = request.get_json()

    # LoRaWAN metadata
    dev_eui   = data.get("deviceInfo", {}).get("devEui")
    timestamp = data.get("time")                        # network-server reception time

    # Decoded payload (populated by decoder.js in TTN/Chirpstack)
    decoded        = data.get("object", {})
    type_code      = decoded.get("type_code")           # raw number — you decode it later
    azimuth        = decoded.get("azimuth")
    node_timestamp = decoded.get("secs_since_midnight")

    # Gateway radio stats (first gateway wins)
    rx_info = data.get("rxInfo", [])
    rssi = snr = None
    if rx_info:
        rssi = rx_info[0].get("rssi")
        snr  = rx_info[0].get("snr")

    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute(
            """
            INSERT INTO detections
                (dev_eui, timestamp, type_code, azimuth, node_timestamp, rssi, snr)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (dev_eui, timestamp, type_code, azimuth, node_timestamp, rssi, snr)
        )
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"DB insert failed, rolled back: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
