import threading
import os
import time
import subprocess
import signal
import sys

def run_node(node_id, http_port, kademlia_port, bootstrap_node=None):
    """Run a blockchain node process with its own ports"""
    env = os.environ.copy()
    env['FLASK_RUN_PORT'] = str(http_port)
    env['KADEMLIA_PORT'] = str(kademlia_port)
    env['HTTP_NODE_ADDRESS'] = f'http://127.0.0.1:{http_port}'
    
    if bootstrap_node:
        env['KADEMLIA_BOOTSTRAP'] = bootstrap_node
    
    print(f"Starting node {node_id} on HTTP port {http_port}, Kademlia port {kademlia_port}")
    
    # Run the node as a separate process
    process = subprocess.Popen(['python', 'node_server.py'], env=env)
    return process

if __name__ == "__main__":
    # Number of nodes to run
    num_nodes = 3
    
    # Start the first node (will be the bootstrap node for others)
    first_http_port = 8000
    first_kademlia_port = 5678
    
    processes = []
    
    # Start the bootstrap node
    bootstrap_process = run_node(0, first_http_port, first_kademlia_port)
    processes.append(bootstrap_process)
    
    # Wait for bootstrap node to start
    time.sleep(5)
    
    # Bootstrap connection string for other nodes
    bootstrap_connection = f"127.0.0.1:{first_kademlia_port}"
    
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