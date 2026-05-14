# 🤖 Gesture Translator — Tradução de Gestos para Comandos 3D

Código desenvolvido no LabSEA para tradução de gestos humanos em comandos espaciais 3D utilizando reconstrução esquelética, mensageria pub/sub e processamento geométrico. Esse microsserviço é um dos que compôe o Sistema de Comando de Robô Hexápode.

## 📌 Visão Geral

O sistema recebe:
- Detecções de gestos
- Reconstruções esqueléticas 3D

E produz:
- Comandos espaciais
- Eventos stop/move
- Projeções no chão

## ⚙️ Tecnologias

- Python 3.9
- RabbitMQ / AMQP
- NumPy
- is-wire

## 📡 Tópicos

Subscrições:
- GestureDetector.1.Detection
- SkeletonDetector.3D.Annotations

Publicações:
- Action.Result

## 🚀 Execução

```bash
pip install -r requirements.txt
python3 gesture-translator.py
```

## 📂 Estrutura

```text
.
├── gesture-translator.py
├── streamChannel.py
└── README.md
```

## 📬 Contato
Para dúvidas ou sugestões, entre em contato com o time do LabSEA.

[Instagram](https://www.instagram.com/labsea.gua/)

[YouTube](https://www.youtube.com/channel/UCpiTMhUtKi3W7QnoOSL9UsQ)

[LinkedIn](www.linkedin.com/in/labsea-ifes-guarapari-b13684409)

[Email](labsea.gua@gmail.com)
