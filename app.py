"""
Monitor de Sistema - Backend Flask + SocketIO
Coleta métricas de CPU, RAM e Disco em tempo real usando psutil.
"""

import json
import time
import threading
import platform
from collections import deque
from datetime import datetime

import psutil
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

# Tenta importar WMI (disponível apenas no Windows)
try:
    import wmi
    WMI_DISPONIVEL = True
except ImportError:
    WMI_DISPONIVEL = False

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


def coletar_info_hardware():
    """Coleta informações detalhadas de hardware: CPU, RAM e Disco.

    Usa WMI no Windows para obter dados precisos (tipo DDR, modelo NVMe, etc.).
    Em Linux/Mac, utiliza platform e psutil como fallback.
    Esta função deve ser chamada uma única vez na inicialização.
    """
    info = {
        "cpu": {"nome": "Desconhecido", "fabricante": "Desconhecido"},
        "ram": {"tipo": "Desconhecido", "velocidade": "—", "slots": []},
        "discos": [],
    }

    if WMI_DISPONIVEL:
        # ── Windows: detecção via WMI ────────────────────────────────────────
        try:
            c = wmi.WMI()

            # CPU
            for proc in c.Win32_Processor():
                nome = proc.Name.strip() if proc.Name else "Desconhecido"
                fabricante = "Intel" if "Intel" in nome else ("AMD" if "AMD" in nome else "Desconhecido")
                info["cpu"] = {"nome": nome, "fabricante": fabricante}
                break  # usa apenas o primeiro processador

            # RAM — mapeamento de SMBIOSMemoryType para nome do padrão DDR
            TIPOS_RAM = {
                0: "Desconhecido", 20: "DDR", 21: "DDR2",
                24: "DDR3", 26: "DDR4", 34: "DDR5",
            }
            slots = []
            for modulo in c.Win32_PhysicalMemory():
                tipo_id = int(modulo.SMBIOSMemoryType or 0)
                tipo_nome = TIPOS_RAM.get(tipo_id, "Desconhecido")
                velocidade = int(modulo.Speed or 0)
                capacidade_gb = round(int(modulo.Capacity or 0) / (1024 ** 3), 1)
                slots.append({
                    "capacidade_gb": capacidade_gb,
                    "velocidade": velocidade,
                    "tipo": tipo_nome,
                })
            if slots:
                # Usa o tipo e velocidade do primeiro módulo como representativo
                tipo_rep = slots[0]["tipo"]
                vel_rep = slots[0]["velocidade"]
                info["ram"] = {
                    "tipo": tipo_rep,
                    "velocidade": f"{vel_rep} MHz" if vel_rep else "—",
                    "slots": slots,
                }

            # Discos físicos
            for drive in c.Win32_DiskDrive():
                modelo = (drive.Model or "").strip()
                interface = (drive.InterfaceType or "").strip()
                tamanho = int(drive.Size or 0)
                tamanho_gb = round(tamanho / (1024 ** 3), 1) if tamanho else 0.0

                # Detecta tipo de armazenamento pelo modelo
                modelo_upper = modelo.upper()
                if "NVME" in modelo_upper:
                    tipo_disco = "NVMe SSD"
                elif "SSD" in modelo_upper:
                    tipo_disco = "SSD SATA"
                else:
                    tipo_disco = "HDD SATA"

                info["discos"].append({
                    "modelo": modelo,
                    "tipo": tipo_disco,
                    "interface": interface,
                    "tamanho_gb": tamanho_gb,
                })

        except Exception as exc:
            # Falha silenciosa — mantém valores padrão; registra para diagnóstico
            app.logger.warning("Falha ao coletar hardware via WMI: %s", exc)

    else:
        # ── Fallback cross-platform (Linux / macOS) ──────────────────────────
        nome_cpu = platform.processor() or "Desconhecido"
        fabricante = "Intel" if "Intel" in nome_cpu else ("AMD" if "AMD" in nome_cpu else "Desconhecido")
        info["cpu"] = {"nome": nome_cpu, "fabricante": fabricante}

        # RAM: psutil não fornece tipo DDR — exibe capacidade total apenas
        mem = psutil.virtual_memory()
        info["ram"] = {
            "tipo": "Desconhecido",
            "velocidade": "—",
            "slots": [{"capacidade_gb": round(mem.total / (1024 ** 3), 1), "velocidade": 0, "tipo": "Desconhecido"}],
        }

        # Discos: tenta identificar NVMe pelo nome do dispositivo
        try:
            import subprocess
            resultado = subprocess.run(
                ["lsblk", "-d", "-o", "NAME,ROTA,MODEL", "--noheadings"],
                capture_output=True, text=True, timeout=3
            )
            for linha in resultado.stdout.strip().splitlines():
                partes = linha.split(None, 2)
                if len(partes) >= 2:
                    nome_dev = partes[0]
                    rotacional = partes[1]
                    modelo = partes[2].strip() if len(partes) > 2 else nome_dev
                    nome_upper = nome_dev.upper()
                    modelo_upper = modelo.upper()
                    if "NVME" in nome_upper or "NVME" in modelo_upper:
                        tipo_disco = "NVMe SSD"
                    elif rotacional == "0":
                        tipo_disco = "SSD SATA"
                    else:
                        tipo_disco = "HDD SATA"
                    info["discos"].append({
                        "modelo": modelo,
                        "tipo": tipo_disco,
                        "interface": "NVMe" if "NVME" in nome_upper else "SATA",
                        "tamanho_gb": 0.0,
                    })
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # lsblk não disponível nesta plataforma
        except Exception as exc:
            app.logger.warning("Falha ao detectar discos via lsblk: %s", exc)

    return info


# Coleta de hardware uma única vez na inicialização (evita impacto a cada 2s)
_cache_hardware = None


def obter_info_hardware():
    """Retorna o cache de hardware, coletando na primeira chamada."""
    global _cache_hardware
    if _cache_hardware is None:
        _cache_hardware = coletar_info_hardware()
    return _cache_hardware


def coletar_info_sistema():
    """Coleta informações gerais do sistema: hostname, OS e uptime."""
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
        "hardware": obter_info_hardware(),
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
