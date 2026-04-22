import psycopg2
from psycopg2.extras import execute_values
import os
from flask import Flask, request, jsonify, render_template
from database import connect_to_database, close_db_connection

# ===== NEW IMPORTS =====
import math
import numpy as np
from threading import Lock
from flask_socketio import SocketIO

app = Flask(__name__)

# ===== NEW SOCKET =====
socketio = SocketIO(app, cors_allowed_origins="*")

# ===== NEW GLOBAL STATE =====
nodes_cache = {}
latest_detections = {}
lock = Lock()

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

# ===== NEW CACHE LOADER =====
def load_nodes_cache():
    cursor, conn = None, None
    global nodes_cache
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return

        cursor.execute("SELECT dev_eui, latitude, longitude, range FROM nodes")
        rows = cursor.fetchall()

        nodes_cache = {
            row[0]: {
                "lat": row[1],
                "lon": row[2],
                "range": row[3]
            }
            for row in rows
        }

    except Exception as e:
        app.logger.error(f"Error loading node cache: {e}")
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

def update_node_connections(cursor):
    cursor.execute("""
        UPDATE nodes n
        SET connected_gateway = (
            SELECT g.gateway_id
            FROM gateways g
            ORDER BY POWER(n.latitude - g.latitude, 2) + POWER(n.longitude - g.longitude, 2) ASC
            LIMIT 1
        )
    """)

# ===== GEOMETRY =====
def azimuth_to_vector(azimuth_deg):
    theta = math.radians(azimuth_deg)
    return math.sin(theta), math.cos(theta)

def latlon_to_xy(lat, lon, ref_lat):
    R = 6371000
    x = math.radians(lon) * R * math.cos(math.radians(ref_lat))
    y = math.radians(lat) * R
    return x, y

def xy_to_latlon(x, y, ref_lat):
    R = 6371000
    lat = math.degrees(y / R)
    lon = math.degrees(x / (R * math.cos(math.radians(ref_lat))))
    return lat, lon

def estimate_position(lines):
    A, b = [], []
    for x0, y0, dx, dy in lines:
        A.append([dy, -dx])
        b.append(dy * x0 - dx * y0)

    A = np.array(A)
    b = np.array(b)

    pos, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    return pos

# =========================================================
# NODES
# =========================================================

@app.route("/nodes", methods=["GET"])
def get_nodes():
    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute("SELECT dev_eui, name, latitude, longitude, altitude, range, connected_gateway FROM nodes")
        rows = cursor.fetchall()
        
        nodes = []
        for row in rows:
            nodes.append({
                "dev_eui": row[0],
                "name": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "altitude": row[4],
                "range": row[5],
                "connected_gateway": row[6]
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
        update_node_connections(cursor)
        conn.commit()
        load_nodes_cache()

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
            
        update_node_connections(cursor)
        conn.commit()
        load_nodes_cache()

    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"DB update failed, rolled back: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok"}), 200

@app.route("/nodes/<dev_eui>", methods=["DELETE"])
def delete_node(dev_eui):
    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        cursor.execute("DELETE FROM nodes WHERE dev_eui=%s", (dev_eui,))
        
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Node not found"}), 404
            
        update_node_connections(cursor)
        conn.commit()
        load_nodes_cache()

    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"DB delete failed, rolled back: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok"}), 200

# =========================================================
# UPLINK (FULL + REALTIME)
# =========================================================

@app.route("/uplink", methods=["POST"])
def uplink():
    event = request.args.get("event")
    if event != "up":
        return jsonify({"status": "ignored", "event": event}), 200

    try:
        data = request.get_json()
    except Exception as e:
        app.logger.error(f"Failed to parse JSON: {e}")
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    dev_eui = data.get("deviceInfo", {}).get("devEui")
    timestamp = data.get("time")

    decoded = data.get("object", {})
    detections = decoded.get("detections", [])

    if not detections:
        return jsonify({"status": "ok", "message": "No detections to process"}), 200

    insert_values = []
    for det in detections:
        insert_values.append((
            dev_eui,
            timestamp,
            det.get("type_code"),
            det.get("azimuth"),
            det.get("secs_since_midnight"),
            None,
            None
        ))

    cursor, conn = None, None
    try:
        cursor, conn = connect_to_database()
        if not conn or not cursor:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500

        execute_values(cursor, """
            INSERT INTO detections
            (dev_eui, timestamp, type_code, azimuth, node_timestamp, rssi, snr)
            VALUES %s
        """, insert_values)

        conn.commit()

        # ===== REAL-TIME =====
        results = []

        with lock:
            for det in detections:
                key = (det.get("type_code"), int(det.get("secs_since_midnight", 0)//2))
                latest_detections.setdefault(key, []).append((dev_eui, det.get("azimuth")))

            if nodes_cache:
                ref_lat = list(nodes_cache.values())[0]["lat"]

                for (type_code, _), group in latest_detections.items():
                    if len(group) < 2:
                        continue

                    lines = []
                    node_positions = []

                    for dev, az in group:
                        node = nodes_cache.get(dev)
                        if not node:
                            continue

                        x, y = latlon_to_xy(node["lat"], node["lon"], ref_lat)
                        dx, dy = azimuth_to_vector(az)

                        lines.append((x, y, dx, dy))
                        node_positions.append({
                            "dev_eui": dev,
                            "lat": node["lat"],
                            "lon": node["lon"]
                        })

                    if len(lines) < 2:
                        continue

                    tx, ty = estimate_position(lines)
                    lat, lon = xy_to_latlon(tx, ty, ref_lat)

                    results.append({
                        "type": type_code,
                        "target": {"latitude": lat, "longitude": lon},
                        "nodes": node_positions
                    })

        if results:
            socketio.emit("new_estimate", results)

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        app.logger.error(f"Database error during bulk insert: {e}")
        return jsonify({"status": "error", "message": "Database communication error"}), 500

    except Exception as e:
        if conn:
            conn.rollback()
        app.logger.error(f"Unexpected error during bulk insert: {e}")
        return jsonify({"status": "error", "message": "Unexpected server error"}), 500

    finally:
        if cursor and conn:
            close_db_connection(cursor, conn)

    return jsonify({"status": "ok", "inserted": len(insert_values)}), 200

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    load_nodes_cache()
    socketio.run(app, host="0.0.0.0", port=5000)