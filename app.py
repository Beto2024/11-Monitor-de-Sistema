"""
Monitor de Sistema - Backend Flask + SocketIO
Coleta métricas de CPU, RAM e Disco em tempo real usando psutil.
"""

import json
import time
import threading
from collections import deque
from datetime import datetime

import psutil
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

# ---------------------------------------------------------------------------
# Configuração da aplicação
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = "monitor-de-sistema-secret"

# Inicializa SocketIO com suporte a CORS para desenvolvimento local
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ---------------------------------------------------------------------------
# Armazenamento de histórico em memória (últimas 60 leituras ≈ 2 minutos)
# ---------------------------------------------------------------------------

HISTORICO_MAX = 60
historico_metricas = deque(maxlen=HISTORICO_MAX)

# ---------------------------------------------------------------------------
# Configuração padrão de alertas (thresholds em %)
# ---------------------------------------------------------------------------

alertas_config = {
    "cpu": 80,
    "ram": 80,
    "disco": 80,
}

# ---------------------------------------------------------------------------
# Funções de coleta de métricas
# ---------------------------------------------------------------------------


def coletar_metricas_cpu():
    """Coleta métricas de CPU: percentual total, por core e frequência."""
    uso_total = psutil.cpu_percent(interval=None)
    uso_por_core = psutil.cpu_percent(interval=None, percpu=True)

    freq = psutil.cpu_freq()
    frequencia = {
        "atual": round(freq.current, 1) if freq else 0,
        "minima": round(freq.min, 1) if freq else 0,
        "maxima": round(freq.max, 1) if freq else 0,
    }

    return {
        "total": uso_total,
        "por_core": uso_por_core,
        "nucleos_logicos": psutil.cpu_count(logical=True),
        "nucleos_fisicos": psutil.cpu_count(logical=False),
        "frequencia": frequencia,
    }


def coletar_metricas_ram():
    """Coleta métricas de memória RAM: total, usada, disponível e percentual."""
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "usada": mem.used,
        "disponivel": mem.available,
        "percentual": mem.percent,
        "total_gb": round(mem.total / (1024**3), 2),
        "usada_gb": round(mem.used / (1024**3), 2),
        "disponivel_gb": round(mem.available / (1024**3), 2),
    }


def coletar_metricas_disco():
    """Coleta métricas de disco para cada partição montada."""
    particoes = []
    for part in psutil.disk_partitions(all=False):
        try:
            uso = psutil.disk_usage(part.mountpoint)
            particoes.append(
                {
                    "dispositivo": part.device,
                    "ponto_montagem": part.mountpoint,
                    "sistema_arquivos": part.fstype,
                    "total_gb": round(uso.total / (1024**3), 2),
                    "usado_gb": round(uso.used / (1024**3), 2),
                    "livre_gb": round(uso.free / (1024**3), 2),
                    "percentual": uso.percent,
                }
            )
        except PermissionError:
            # Ignora partições sem permissão de leitura
            continue

    return particoes


def coletar_info_sistema():
    """Coleta informações gerais do sistema: hostname, OS e uptime."""
    import platform
    import socket

    tempo_boot = psutil.boot_time()
    uptime_segundos = int(time.time() - tempo_boot)
    horas, resto = divmod(uptime_segundos, 3600)
    minutos, segundos = divmod(resto, 60)

    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arquitetura": platform.machine(),
        "uptime": f"{horas:02d}:{minutos:02d}:{segundos:02d}",
        "uptime_segundos": uptime_segundos,
        "python_version": platform.python_version(),
    }


def coletar_top_processos(limite=5):
    """Coleta os top N processos por uso de CPU."""
    processos = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processos.append(
                {
                    "pid": info["pid"],
                    "nome": info["name"],
                    "cpu": round(info["cpu_percent"] or 0, 1),
                    "ram": round(info["memory_percent"] or 0, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Ordena por CPU decrescente e retorna os top N
    processos.sort(key=lambda x: x["cpu"], reverse=True)
    return processos[:limite]


def coletar_todas_metricas():
    """Agrega todas as métricas em um único dicionário."""
    metricas = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_unix": time.time(),
        "cpu": coletar_metricas_cpu(),
        "ram": coletar_metricas_ram(),
        "disco": coletar_metricas_disco(),
        "sistema": coletar_info_sistema(),
        "processos": coletar_top_processos(),
    }
    return metricas


def verificar_alertas(metricas):
    """Verifica se alguma métrica ultrapassou o threshold configurado."""
    alertas_ativos = []

    if metricas["cpu"]["total"] >= alertas_config["cpu"]:
        alertas_ativos.append(
            {
                "tipo": "cpu",
                "valor": metricas["cpu"]["total"],
                "threshold": alertas_config["cpu"],
                "mensagem": f"CPU em {metricas['cpu']['total']}% (limite: {alertas_config['cpu']}%)",
            }
        )

    if metricas["ram"]["percentual"] >= alertas_config["ram"]:
        alertas_ativos.append(
            {
                "tipo": "ram",
                "valor": metricas["ram"]["percentual"],
                "threshold": alertas_config["ram"],
                "mensagem": f"RAM em {metricas['ram']['percentual']}% (limite: {alertas_config['ram']}%)",
            }
        )

    for particao in metricas["disco"]:
        if particao["percentual"] >= alertas_config["disco"]:
            alertas_ativos.append(
                {
                    "tipo": "disco",
                    "valor": particao["percentual"],
                    "threshold": alertas_config["disco"],
                    "mensagem": (
                        f"Disco {particao['ponto_montagem']} em "
                        f"{particao['percentual']}% (limite: {alertas_config['disco']}%)"
                    ),
                }
            )

    return alertas_ativos


# ---------------------------------------------------------------------------
# Thread de coleta contínua de métricas
# ---------------------------------------------------------------------------


def loop_coleta_metricas():
    """Thread principal que coleta métricas a cada 2 segundos e emite via WebSocket."""
    # Primeira chamada ao cpu_percent para calibrar os contadores internos.
    # É necessária porque cpu_percent compara leituras consecutivas:
    # na primeira chamada, sem medição anterior, retorna 0.0 para todos os cores.
    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(1)

    while True:
        try:
            metricas = coletar_todas_metricas()
            historico_metricas.append(metricas)

            # Emite métricas para todos os clientes conectados
            socketio.emit("metricas", metricas)

            # Verifica e emite alertas, se houver
            alertas = verificar_alertas(metricas)
            if alertas:
                socketio.emit("alertas", alertas)

        except Exception as e:
            app.logger.error(f"Erro ao coletar métricas: {e}")

        time.sleep(2)


# ---------------------------------------------------------------------------
# Rotas REST
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    """Serve o dashboard principal."""
    return render_template("index.html")


@app.route("/api/metrics")
def api_metricas():
    """Retorna as métricas mais recentes em JSON."""
    if historico_metricas:
        return jsonify(historico_metricas[-1])
    metricas = coletar_todas_metricas()
    return jsonify(metricas)


@app.route("/api/history")
def api_historico():
    """Retorna o histórico de métricas armazenadas em memória."""
    return jsonify(list(historico_metricas))


@app.route("/api/alerts", methods=["GET"])
def api_alertas_get():
    """Retorna a configuração atual de alertas."""
    return jsonify(alertas_config)


@app.route("/api/alerts", methods=["POST"])
def api_alertas_post():
    """Atualiza a configuração de alertas via JSON."""
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Payload JSON inválido"}), 400

    erros = []
    for campo in ("cpu", "ram", "disco"):
        if campo in dados:
            try:
                valor = float(dados[campo])
                if not (0 <= valor <= 100):
                    erros.append(f"'{campo}' deve estar entre 0 e 100")
                else:
                    alertas_config[campo] = valor
            except (TypeError, ValueError):
                erros.append(f"'{campo}' deve ser um número")

    if erros:
        return jsonify({"erros": erros}), 400

    # Notifica clientes sobre a nova configuração
    socketio.emit("alertas_config", alertas_config)
    return jsonify({"sucesso": True, "config": alertas_config})


# ---------------------------------------------------------------------------
# Eventos WebSocket
# ---------------------------------------------------------------------------


@socketio.on("connect")
def ao_conectar():
    """Envia as métricas e configuração imediatamente ao conectar."""
    if historico_metricas:
        socketio.emit("metricas", historico_metricas[-1])
    socketio.emit("alertas_config", alertas_config)
    socketio.emit("historico", list(historico_metricas))


@socketio.on("solicitar_historico")
def ao_solicitar_historico():
    """Responde à solicitação explícita de histórico."""
    socketio.emit("historico", list(historico_metricas))


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Inicia thread de coleta em background (daemon=True para encerrar com o processo)
    thread_coleta = threading.Thread(target=loop_coleta_metricas, daemon=True)
    thread_coleta.start()

    print("=" * 50)
    print("  Monitor de Sistema - Dashboard em Tempo Real")
    print("  Acesse: http://localhost:5000")
    print("=" * 50)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
