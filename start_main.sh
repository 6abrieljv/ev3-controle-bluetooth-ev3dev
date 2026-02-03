cat > /home/robot/start_main.sh <<'EOF'
#!/bin/sh
# espera até 30s por /dev/input/event* (ajuste se quiser)
for i in $(seq 1 30); do
  if ls /dev/input/event* >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
exec /usr/bin/python3 /home/robot/main.py
EOF
chmod +x /home/robot/start_main.sh