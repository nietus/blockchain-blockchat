import threading
import os
import time
import subprocess
import signal
import sys
import socket

def run_node(node_id, http_port, kademlia_port, bootstrap_node=None):
    """Run a blockchain node process with its own ports"""
    env = os.environ.copy()
    
    # Determine if we're running in Railway
    in_railway = 'RAILWAY_STATIC_URL' in os.environ
    main_port = os.environ.get('PORT', '8080')  # Railway assigns this PORT
    railway_url = 'https://blockchain-bc-production.up.railway.app'
    
    if in_railway:
        # In Railway, we use the same port but different URL paths
        env['FLASK_RUN_PORT'] = main_port
        # Each node gets a different URL prefix
        env['NODE_PREFIX'] = f'/node{node_id}'
        # Set HTTP address to the external Railway URL with the node prefix
        env['HTTP_NODE_ADDRESS'] = f"{railway_url}/node{node_id}"
        # We'll still use different Kademlia ports internally
        env['KADEMLIA_PORT'] = str(kademlia_port)
        
        # Debug info for Railway deployment
        print(f"Railway deployment: Node {node_id} HTTP address set to {env['HTTP_NODE_ADDRESS']}")
    else:
        # For local development, use different ports
        env['FLASK_RUN_PORT'] = str(http_port)
        env['HTTP_NODE_ADDRESS'] = f'http://127.0.0.1:{http_port}'
        env['KADEMLIA_PORT'] = str(kademlia_port)
        env['NODE_PREFIX'] = ''  # No prefix needed locally
    
    if bootstrap_node:
        env['KADEMLIA_BOOTSTRAP'] = bootstrap_node
    
    print(f"Starting node {node_id} - HTTP: {env['HTTP_NODE_ADDRESS']}, Kademlia port: {kademlia_port}")
    
    # Run the node as a separate process
    if in_railway:
        # On Railway, we need to create proxy Flask apps to handle different paths
        process = subprocess.Popen(['python', 'railway_node_server.py', str(node_id)], env=env)
    else:
        # Locally, we can run the node_server.py directly
        process = subprocess.Popen(['python', 'node_server.py'], env=env)
    
    return process

if __name__ == "__main__":
    # Check if running in Railway
    in_railway = 'RAILWAY_STATIC_URL' in os.environ
    
    # Number of nodes to run
    num_nodes = 3
    
    # Base ports 
    first_http_port = 8000
    first_kademlia_port = 5678
    
    processes = []
    
    # Start the bootstrap node
    bootstrap_process = run_node(0, first_http_port, first_kademlia_port)
    processes.append(bootstrap_process)
    
    # Wait for bootstrap node to start
    time.sleep(5)
    
    # Bootstrap connection string for other nodes
    # In Railway or local, we use the local IP for Kademlia
    host = socket.gethostname() if in_railway else '127.0.0.1'
    
    # Get more reliable IP for Docker/container environments
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        host = ip
    except Exception as e:
        print(f"Error getting IP address: {e}, falling back to hostname")
    
    bootstrap_connection = f"{host}:{first_kademlia_port}"
    print(f"Bootstrap connection string: {bootstrap_connection}")
    
    # Start additional nodes
    for i in range(1, num_nodes):
        http_port = first_http_port + i
        kademlia_port = first_kademlia_port + i
        
        node_process = run_node(i, http_port, kademlia_port, bootstrap_connection)
        processes.append(node_process)
        
        # Give each node time to start up
        time.sleep(2)
    
    print(f"Started {num_nodes} blockchain nodes")
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("Shutting down all nodes...")
        for p in processes:
            p.terminate()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None) 