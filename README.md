# 1: setup the environment
python3 -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip && pip install -r requirements.txt

Replace the file path with yours. "cd /Users/manikkugenileshsaumyadasa/Downloads/cloudfs"


# 2: Start the Server (Then go to the IP address mentioned in the temrnial to run locally)
python server.py

# Initiate tailscale tunnel in new terminal (If need to access another pc in any other network)
tailscale funnel 8080
