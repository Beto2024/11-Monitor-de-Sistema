"""
Monitor de Sistema - Dashboard em tempo real
Tecnologias: Python, Flask, WebSockets, psutil
"""

import json
import time
import threading
from datetime import datetime
from collections import deque

from flask import Flask, render_template, jsonify, request
from flask_sock import Sock
import psutil

app = Flask(__name__)
sock = Sock(app)

# ---------------------------------------------------------------------------
# Configuracoes de alertas (padrao)
# ---------------------------------------------------------------------------
alerts_config = {
    "cpu": {"enabled": True, "threshold": 80},
    "memory": {"enabled": True, "threshold": 85},
    "disk": {"enabled": True, "threshold": 90},
}

# ---------------------------------------------------------------------------
# Historico de metricas (ultimos 60 pontos = 5 min com intervalo de 5 s)
# ---------------------------------------------------------------------------
MAX_HISTORY = 60
metrics_history = {
    "timestamps": deque(maxlen=MAX_HISTORY),
    "cpu": deque(maxlen=MAX_HISTORY),
    "memory": deque(maxlen=MAX_HISTORY),
    "disk": deque(maxlen=MAX_HISTORY),
}

alerts_log: list[dict] = []
MAX_ALERTS = 50

ws_clients: list = []
ws_lock = threading.Lock()

def collect_metrics() -> dict:
    """Coleta metricas atuais do sistema."""
    cpu_percent = psutil.cpu_percent(interval=0)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    cpu_freq = psutil.cpu_freq()
    freq_current = round(cpu_freq.current, 0) if cpu_freq else 0

    metrics = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "cpu": {
            "percent": cpu_percent,
            "cores_logical": psutil.cpu_count(logical=True),
            "cores_physical": psutil.cpu_count(logical=False),
            "freq_mhz": freq_current,
        },
        "memory": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
        },
        "disk": {
            "percent": disk.percent,
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
        },
    }
    return metrics

def check_alerts(metrics: dict) -> list[dict]:
    """Verifica se alguma metrica ultrapassou o limiar configurado."""
    triggered = []
    now = datetime.now().strftime("%H:%M:%S")

    mapping = {
        "cpu": metrics["cpu"]["percent"],
        "memory": metrics["memory"]["percent"],
        "disk": metrics["disk"]["percent"],
    }

    labels = {"cpu": "CPU", "memory": "Memoria RAM", "disk": "Disco"}

    for key, value in mapping.items():
        cfg = alerts_config[key]
        if cfg["enabled"] and value >= cfg["threshold"]:
            alert = {
                "time": now,
                "type": key,
                "label": labels[key],
                "value": value,
                "threshold": cfg["threshold"],
                "message": (
                    f"{labels[key]} em {value}% - "
                    f"acima do limiar de {cfg['threshold']}%"
                ),
            }
            triggered.append(alert)

    return triggered

def background_collector():
    """Thread que coleta metricas a cada 5 segundos e envia via WS."""
    psutil.cpu_percent(interval=1)

    while True:
        metrics = collect_metrics()

        metrics_history["timestamps"].append(metrics["timestamp"])
        metrics_history["cpu"].append(metrics["cpu"]["percent"])
        metrics_history["memory"].append(metrics["memory"]["percent"])
        metrics_history["disk"].append(metrics["disk"]["percent"])

        new_alerts = check_alerts(metrics)
        for a in new_alerts:
            alerts_log.insert(0, a)
        while len(alerts_log) > MAX_ALERTS:
            alerts_log.pop()

        payload = json.dumps(
            {
                "metrics": metrics,
                "alerts": new_alerts,
                "history": {
                    "timestamps": list(metrics_history["timestamps"]),
                    "cpu": list(metrics_history["cpu"]),
                    "memory": list(metrics_history["memory"]),
                    "disk": list(metrics_history["disk"]),
                },
            }
        )

        with ws_lock:
            disconnected = []
            for ws in ws_clients:
                try:
                    ws.send(payload)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                ws_clients.remove(ws)

        time.sleep(5)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/metrics")
def api_metrics():
    return jsonify(collect_metrics())

@app.route("/api/history")
def api_history():
    return jsonify(
        {
            "timestamps": list(metrics_history["timestamps"]),
            "cpu": list(metrics_history["cpu"]),
            "memory": list(metrics_history["memory"]),
            "disk": list(metrics_history["disk"]),
        }
    )

@app.route("/api/alerts", methods=["GET"])
def api_alerts_get():
    return jsonify({"config": alerts_config, "log": alerts_log[:20]})

@app.route("/api/alerts", methods=["POST"])
def api_alerts_set():
    data = request.get_json(force=True)
    for key in ("cpu", "memory", "disk"):
        if key in data:
            if "enabled" in data[key]:
                alerts_config[key]["enabled"] = bool(data[key]["enabled"])
            if "threshold" in data[key]:
                alerts_config[key]["threshold"] = int(data[key]["threshold"])
    return jsonify({"status": "ok", "config": alerts_config})

@sock.route("/ws")
def websocket(ws):
    with ws_lock:
        ws_clients.append(ws)
    try:
        while True:
            ws.receive(timeout=60)
    except Exception:
        pass
    finally:
        with ws_lock:
            if ws in ws_clients:
                ws_clients.remove(ws)

collector_thread = threading.Thread(target=background_collector, daemon=True)
collector_thread.start()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)