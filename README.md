# 🤖 EV3 - Controle Bluetooth com EV3dev

Controle motores do EV3 com controle Bluetooth ou USB (PS4, PS3, Xbox, etc). O
programa roda como servico systemd e mostra um menu na tela do EV3: da para
parear o controle e dirigir usando so os botoes do bloco.

## 🖥️ Menu na tela do EV3

Ligou o EV3, o menu aparece sozinho. Tudo pelos botoes do bloco:
**CIMA/BAIXO** escolhe, **ENTER** abre, **VOLTAR** volta/cancela.

| Opcao | O que faz |
|---|---|
| **Dirigir** | usa o controle conectado (aperte PS no controle) |
| **Parear controle** | qualquer controle Bluetooth (PS4 ou universal): ponha em modo pareamento, escolha na lista e aperte ENTER |
| **Parear PS3** | ligue o controle no USB, tire o cabo e aperte PS |
| **Rede** | mostra o IP e conecta o Wi-Fi salvo ou o Bluetooth do PC (para usar o ssh) |
| **Info** | IP, bateria e controle conectado |
| **Brickman** | abre o menu normal do ev3dev (reinicie o EV3 para voltar) |
| **Desligar** | desliga o EV3 |

O rodape do menu mostra se tem controle conectado. Se o programa parar por
qualquer motivo, o systemd abre ele de novo em 3 segundos.

## 🎮 Dirigindo

| Controle | Acao |
|---|---|
| Analogico esquerdo CIMA/BAIXO | frente / re |
| Analogico esquerdo ESQ/DIR | vira |
| **X** (PS4) | volta ao menu |
| Segurar **START** 1 s e soltar (PS3 e controles genericos) | volta ao menu |
| **VOLTAR** no EV3 | volta ao menu |

Se o controle desconectar, o robo para e espera ele voltar (aperte PS).

Motores: **B** = esquerdo, **C** = direito (mude `MOTOR_LEFT`/`MOTOR_RIGHT` no
`main.py`). Se andar ao contrario, use `INVERT_THROTTLE` / `INVERT_TURN`.

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

## 🎮 Parear pelo terminal/Brickman (alternativa)

O jeito facil e pelo menu (**Parear controle** / **Parear PS3**). Se preferir:

### PS4


1. Se o programa estiver rodando: `sudo systemctl start brickman`
2. No controle, segure **SHARE + PS** ate a luz piscar rapido (duas piscadas
   seguidas).
3. No EV3: **Wireless and Networks > Bluetooth** (Powered marcado) > **Start
   Scan** > escolha **Wireless Controller** > **Pair**.
4. Reinicie o EV3 (`sudo reboot`). Depois e so apertar **PS** no controle.

Pelo terminal:
```
sudo systemctl stop ev3main.service
bluetoothctl
  power on
  agent on
  default-agent
  scan on                    # com o controle em SHARE+PS
  pair XX:XX:XX:XX:XX:XX     # MAC do "Wireless Controller"
  trust XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  quit
sudo systemctl start ev3main.service
```
No cabo USB tambem funciona, sem parear.

### PS3

O DualShock 3 nao pareia pela busca normal do Bluetooth: ele precisa ser ligado
no cabo uma vez para gravar o endereco do EV3.

#### Pelo Brickman

1. Pare o programa e volte o Brickman:
   ```
   sudo systemctl start brickman
   ```
2. No EV3: **Wireless and Networks > Bluetooth** e deixe **Powered** e
   **Visible** marcados.
3. Ligue o controle no EV3 com cabo mini-USB (porta USB grande, ao lado do SD).
   Deve aparecer "PLAYSTATION(R)3 Controller" em Devices. **Nao clique em
   parear.**
4. Tire o cabo e aperte o botao **PS**.
5. Quando perguntar **"Authorize service HID?"**, escolha **Accept**.
6. Reinicie o EV3 (`sudo reboot`). Pronto: dai pra frente e so ligar o EV3 e
   apertar **PS**.

#### Pelo terminal (bluetoothctl)

```
sudo systemctl stop ev3main.service
bluetoothctl
  power on
  agent on
  default-agent
```
Com o `bluetoothctl` aberto: ligue o controle no cabo USB, espere uns segundos,
tire o cabo e aperte **PS**. Quando aparecer
`Authorize service ... (yes/no)`, digite `yes`. Depois:
```
  devices                 # anote o MAC do controle
  trust XX:XX:XX:XX:XX:XX
  quit
sudo systemctl start ev3main.service
```

### Usando no cabo (sem Bluetooth)

Tambem funciona: ligue o controle na porta USB do EV3 e aperte **PS**.

### Problemas comuns

- **Luzes piscando e nada acontece:** o controle nao foi pareado/autorizado.
  Repita o pareamento.
- **Controle paralelo/chines (SHANWAN, GASIA):** alguns nao pareiam com o
  Bluetooth do ev3dev stretch. Teste no cabo USB.
- **Botoes diferentes do esperado:** rode o teste abaixo e ajuste os codigos em
  `PROFILES` no `main.py`.

## 🔍 Testar botoes e eixos

```
sudo systemctl stop ev3main.service
python3 /home/robot/testar_controle.py
```
Mostra o nome e o codigo de cada botao/eixo que voce mexer.

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
scp .\main.py .\start_main.sh .\ev3main.service .\testar_controle.py robot@ev3dev:/home/robot/
```

No EV3:
```
sed -i 's/\r$//' /home/robot/*.sh /home/robot/*.py /home/robot/ev3main.service
sudo chmod +x /home/robot/start_main.sh
sudo cp /home/robot/ev3main.service /etc/systemd/system/ev3main.service
sudo systemctl disable brickman
sudo systemctl daemon-reload
sudo systemctl enable ev3main.service
sudo systemctl restart ev3main.service
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

## 🧱 Brickman

O deploy desativa o brickman no boot para o menu aparecer sozinho. Ele continua
disponivel pela opcao **Brickman** do menu. Para voltar ao comportamento antigo:
```
sudo systemctl enable brickman
sudo systemctl disable ev3main.service
```

## 🧪 Logs

```
sudo systemctl status ev3main.service --no-pager
sudo journalctl -u ev3main.service -n 50 --no-pager
```

## 🐞 Debug no LCD

Ative no `main.py`:
```
DEBUG_EVENT = True
```

> O `main.py` precisa continuar compativel com Python 3.5 (ev3dev stretch):
> nada de f-strings.

