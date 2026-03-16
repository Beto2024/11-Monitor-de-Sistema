# 📡 Monitor de Sistema

![Status](https://img.shields.io/badge/Status-Em%20Desenvolvimento-blueviolet?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-f59e0b?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-a855f7?style=flat-square&logo=flask&logoColor=white)
![SocketIO](https://img.shields.io/badge/Socket.IO-4.x-ec4899?style=flat-square)
![psutil](https://img.shields.io/badge/psutil-5.9-22c55e?style=flat-square)
![Licença](https://img.shields.io/badge/Licen%C3%A7a-MIT-8b5cf6?style=flat-square)

Dashboard em **tempo real** exibindo métricas de CPU, memória RAM e disco do servidor, com alertas configuráveis e histórico de uso.

---

## 🖼️ Preview

> Dashboard com tema dark, gauges circulares animados, gráficos de histórico e painel de alertas configuráveis.

---

## 🛠️ Tecnologias

| Tecnologia | Função |
|---|---|
| **Python 3.8+** | Linguagem principal do backend |
| **Flask** | Framework web para servir o dashboard |
| **Flask-SocketIO** | Comunicação em tempo real via WebSocket |
| **psutil** | Coleta de métricas do sistema operacional |
| **Chart.js** | Gráficos de histórico no frontend |
| **Socket.IO (JS)** | Cliente WebSocket no browser |

---

## ✨ Funcionalidades

- 📊 **Métricas em tempo real** (atualização a cada 2 segundos)
  - CPU: uso total, por core e frequência
  - RAM: total, usada, disponível e percentual
  - Disco: por partição — total, usado, livre e percentual
- 📈 **Histórico visual** com gráficos de linha (últimos 2 minutos)
- 🔔 **Sistema de alertas** com thresholds configuráveis para CPU, RAM e Disco
- ⚡ **Top 5 processos** por uso de CPU em tempo real
- 🖥️ **Informações do sistema** — hostname, OS, arquitetura e uptime
- 🎨 **Tema dark** com paleta purple/amber/pink e gauges circulares animados

---

## 🚀 Como executar

### 1. Clonar o repositório
```bash
git clone https://github.com/Beto2024/11-Monitor-de-Sistema.git
cd 11-Monitor-de-Sistema
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

### 3. Executar
```bash
python app.py
```

Acesse no navegador: **http://localhost:5000**

---

## 📁 Estrutura do Projeto

```
11-Monitor-de-Sistema/
├── app.py                  # Backend Flask + SocketIO + coleta de métricas
├── requirements.txt        # Dependências Python
├── README.md               # Documentação
├── static/
│   ├── css/
│   │   └── style.css       # Estilos (tema dark)
│   └── js/
│       └── dashboard.js    # Lógica frontend, WebSocket e gráficos
└── templates/
    └── index.html          # Template principal do dashboard
```

---

## 🔔 Configuração de Alertas

Os thresholds padrão são **80%** para CPU, RAM e Disco. Você pode alterá-los:

### Via interface
Use os sliders na seção "Configurar Thresholds" do dashboard e clique em "Salvar Alertas".

### Via API REST
```bash
curl -X POST http://localhost:5000/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"cpu": 90, "ram": 85, "disco": 75}'
```

---

## 📡 API Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Serve o dashboard HTML |
| `GET` | `/api/metrics` | Retorna métricas atuais em JSON |
| `GET` | `/api/history` | Retorna histórico de métricas |
| `GET` | `/api/alerts` | Retorna configuração de alertas |
| `POST` | `/api/alerts` | Atualiza configuração de alertas |

### Exemplo de resposta — `/api/metrics`
```json
{
  "timestamp": "2024-01-15T14:30:00.123456",
  "cpu": {
    "total": 12.5,
    "por_core": [10.0, 15.0, 8.0, 14.0],
    "nucleos_logicos": 4,
    "nucleos_fisicos": 2,
    "frequencia": { "atual": 2400.0, "minima": 400.0, "maxima": 3600.0 }
  },
  "ram": {
    "total_gb": 16.0,
    "usada_gb": 8.5,
    "disponivel_gb": 7.5,
    "percentual": 53.1
  },
  "disco": [
    {
      "ponto_montagem": "/",
      "sistema_arquivos": "ext4",
      "total_gb": 512.0,
      "usado_gb": 200.0,
      "livre_gb": 312.0,
      "percentual": 39.1
    }
  ]
}
```

---

## 📝 Licença

Este projeto está licenciado sob a [MIT License](LICENSE).

---

<p align="center">Feito com 💜 por <a href="https://github.com/Beto2024">Beto2024</a></p>
