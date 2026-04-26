# 1: setup the environment
python3 -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip && pip install -r requirements.txt

# 2. To activate the environment
source .venv/bin/activate

# 3: Start the Server (Then go to the IP address mentioned in the temrnial to run locally or get accessed by devices in the same network)
python server.py

# 4: Initiate tailscale tunnel in new terminal (If need to access from another pc in any other network)
tailscale funnel 8080
