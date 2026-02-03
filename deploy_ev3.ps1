param(
  [string]$HostName = "ev3dev",
  [string]$User = "robot"
)

Write-Host "Deploying files to $User@$HostName..."
Write-Host "Obs: a senha sera solicitada pelo ssh/scp."

# Paths
$files = @("start_main.sh","ev3main.service","main.py")
foreach ($f in $files) {
    if (-not (Test-Path $f)) {
        Write-Error "Local file $f not found. Run this from project folder."
        exit 1
    }
}

# Copy files
$dest = $User + "@" + $HostName + ":/home/" + $User + "/"
$scpCmd = "scp " + ($files -join ' ') + " " + $dest
Write-Host "Copying files with: $scpCmd"
scp @files $dest
if ($LASTEXITCODE -ne 0) { Write-Error "scp failed with exit code $LASTEXITCODE"; exit 1 }

# Remote commands to setup files and service
$remoteCmd = @'
# move service unit
if [ -f /home/$USER/ev3main.service ]; then
  sudo mv /home/$USER/ev3main.service /etc/systemd/system/ev3main.service
fi
# ensure wrapper exists and is executable
if [ -f /home/$USER/start_main.sh ]; then
  sudo chown $USER:$USER /home/$USER/start_main.sh
  sudo chmod +x /home/$USER/start_main.sh
fi
# reload and enable service
sudo systemctl daemon-reload
sudo systemctl enable ev3main.service
sudo systemctl start ev3main.service
sudo systemctl status ev3main.service --no-pager
'@

# Replace $USER placeholder with actual user for remote execution
$remoteCmd = $remoteCmd -replace '\$USER', $User

Write-Host "Running remote setup commands..."
ssh -t $User@$HostName $remoteCmd

Write-Host "Done. If prompted, enter the SSH password for $User@$Host."