# 🤖 EV3 - Controle Bluetooth com EV3dev

Controle motores do EV3 com controle Bluetooth (Xbox/PS4/etc). O programa roda
como servico systemd e mostra uma interface simples no LCD para selecionar o
dispositivo.

## ✅ Requisitos

- EV3 com EV3dev (Debian stretch)
- Python 3
- Pacotes no EV3:
  - `python3-ev3dev2`
  - `python3-evdev`
  - `python3-pil`

Instalar no EV3:
```
sudo apt-get update
sudo apt-get install -y python3-ev3dev2 python3-evdev python3-pil
```

## 💾 Preparar SD (resumo)

1) Baixe a imagem do EV3dev para EV3.
2) Grave no cartao SD com o balenaEtcher.
3) Coloque no EV3 e ligue.

## 🔐 Acesso SSH

- Usuario: `robot`
- Senha: `maker`
- Hostname: `ev3dev`

```
ssh robot@ev3dev
```

## 🚀 Deploy rapido (Windows -> EV3)

No PowerShell:
```
cd C:\Users\clash\Documents\dev\ev3
scp .\main.py .\start_main.sh .\ev3main.service robot@ev3dev:/home/robot/
```

No EV3:
```
sudo chmod +x /home/robot/start_main.sh
sudo cp /home/robot/ev3main.service /etc/systemd/system/ev3main.service
sudo systemctl daemon-reload
sudo systemctl enable ev3main.service
sudo systemctl start ev3main.service
```

## 🧰 Deploy com script

```
.\deploy_ev3.ps1
```

## 🔁 Atualizar so o main.py

```
scp .\main.py robot@ev3dev:/home/robot/main.py
ssh -t robot@ev3dev "sudo systemctl restart ev3main.service"
```

## 🖥️ Interface no LCD

- **CIMA/BAIXO** muda o dispositivo
- **ENTER** confirma

## 🧱 Brickman

```
sudo systemctl stop brickman
```

Para voltar:
```
sudo systemctl start brickman
```

## 🧪 Logs

```
sudo systemctl status ev3main.service --no-pager
sudo journalctl -u ev3main.service -n 50 --no-pager
```

## 🐞 Debug no LCD

Ative:
```
DEBUG_EVENT = True
```

