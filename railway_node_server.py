import os
import sys
import threading
import subprocess
import time
import signal
import socket
from flask import Flask, request, Response
import requests

app = Flask(__name__)

def create_node_prefix(node_id):
    """Create a URL prefix for a node"""
    return f"/node{node_id}"

# Store references to each node's process
node_processes = {}

def start_node(node_id, http_port, kademlia_port, bootstrap_node=None):
    """Start a blockchain node process"""
    env = os.environ.copy()
    
    # Determine if we're running in Railway
    railway_env = os.environ.get('RAILWAY_ENVIRONMENT', '')
    railway_url = os.environ.get('RAILWAY_STATIC_URL', 'https://blockchain-bc-production.up.railway.app/')
    
    # Mark the environment as Railway for child processes
    if railway_env:
        env['RAILWAY_ENVIRONMENT'] = railway_env
    
    # Set environment variables for the node
    env['FLASK_RUN_PORT'] = str(http_port)
    env['KADEMLIA_PORT'] = str(kademlia_port)
    env['NODE_PREFIX'] = f'/node{node_id}'
    
    # Set HTTP address
    if railway_url:
        # Fix the double slash by ensuring railway_url doesn't end with a slash
        if railway_url.endswith('/'):
            railway_url = railway_url[:-1]
        env['HTTP_NODE_ADDRESS'] = f"{railway_url}/node{node_id}"
    else:
        env['HTTP_NODE_ADDRESS'] = f"http://127.0.0.1:{http_port}"
    
    # IMPORTANT: Remove PORT environment variable that would override FLASK_RUN_PORT
    # This ensures each node uses its own port instead of all trying to use the Railway PORT
    if 'PORT' in env:
        del env['PORT']
    
    # Set bootstrap node if provided
    if bootstrap_node:
        env['KADEMLIA_BOOTSTRAP'] = bootstrap_node
    
    print(f"Starting node {node_id} - HTTP: {env['HTTP_NODE_ADDRESS']}, Kademlia port: {kademlia_port}, Flask port: {http_port}")
    
    # Run the node as a separate process
    process = subprocess.Popen(['python', 'node_server.py'], env=env)
    return process

def initialize_nodes(num_nodes=3):
    """Initialize all blockchain nodes"""
    # Base ports 
    first_http_port = 8000
    first_kademlia_port = 5678
    
    # Start the bootstrap node (node 0)
    bootstrap_process = start_node(0, first_http_port, first_kademlia_port)
    node_processes[0] = bootstrap_process
    
    # Wait for bootstrap node to start
    time.sleep(5)
    
    # Bootstrap connection string for other nodes
    host = socket.gethostname()
    bootstrap_connection = f"{host}:{first_kademlia_port}"
    
    # Start additional nodes
    for i in range(1, num_nodes):
        http_port = first_http_port + i
        kademlia_port = first_kademlia_port + i
        
        node_process = start_node(i, http_port, kademlia_port, bootstrap_connection)
        node_processes[i] = node_process
        
        # Give each node time to start up
        time.sleep(2)
    
    print(f"Started {num_nodes} blockchain nodes")

@app.route('/', methods=['GET'])
def home():
    """Root endpoint showing status of all nodes"""
    nodes_info = ""
    for node_id in node_processes:
        prefix = create_node_prefix(node_id)
        nodes_info += f"<li><a href='{prefix}/chain'>Node {node_id} - View Blockchain</a></li>"
    
    return f"""
    <html>
    <head><title>Multi-Node Blockchain</title></head>
    <body>
        <h1>Multi-Node Blockchain Network</h1>
        <p>This is a multi-node blockchain network running on Railway.</p>
        <h2>Available Nodes:</h2>
        <ul>
            {nodes_info}
        </ul>
    </body>
    </html>
    """

@app.route('/node<int:node_id>/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy_to_node(node_id, subpath):
    """Proxy requests to the appropriate node"""
    # Ensure node ID is valid
    if node_id not in node_processes:
        return f"Node {node_id} not found", 404
    
    # Forward the request to the node
    try:
        # Use the correct port for each node
        http_port = 8000 + node_id
        
        # Include node prefix in URL path for routing through the blueprint
        node_prefix = f"/node{node_id}"
        url = f"http://127.0.0.1:{http_port}{node_prefix}/{subpath}"
        
        print(f"Proxying {request.method} request from {request.path} to {url}")
        
        # Get the data and headers from the original request
        headers = {k: v for k, v in request.headers if k != 'Host'}
        data = request.get_data()
        
        # Make the request to the internal node
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=data,
            params=request.args,
            timeout=10  # Add a timeout to prevent hanging
        )
        
        # Return the response from the node
        return Response(
            response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )
    except Exception as e:
        print(f"Error proxying request to Node {node_id} at port {http_port}: {str(e)}")
        return f"Error proxying request to Node {node_id}: {str(e)}", 500

def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    print("Shutting down all nodes...")
    for node_id, process in node_processes.items():
        if process:
            process.terminate()
    sys.exit(0)

def wait_for_nodes_to_be_ready(timeout=60):
    """Wait for all nodes to be ready and responding"""
    start_time = time.time()
    ready_nodes = set()
    
    print("Waiting for nodes to be ready...")
    
    while time.time() - start_time < timeout and len(ready_nodes) < len(node_processes):
        for node_id in node_processes:
            if node_id in ready_nodes:
                continue
                
            http_port = 8000 + node_id
            try:
                # Try to connect to the node with its node prefix
                node_prefix = f"/node{node_id}"
                response = requests.get(f"http://127.0.0.1:{http_port}{node_prefix}/", timeout=1)
                if response.status_code < 500:  # Accept any non-server error response
                    ready_nodes.add(node_id)
                    print(f"Node {node_id} is ready on port {http_port}")
            except requests.RequestException:
                # Node not ready yet
                pass
                
        if len(ready_nodes) < len(node_processes):
            time.sleep(1)
    
    if len(ready_nodes) == len(node_processes):
        print("All nodes are ready!")
        return True
    else:
        print(f"Timed out waiting for nodes. Only {len(ready_nodes)}/{len(node_processes)} nodes are ready.")
        return False

if __name__ == "__main__":
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Initialize nodes
    num_nodes = 3  # Default to 3 nodes
    print(f"Initializing {num_nodes} blockchain nodes...")
    initialize_nodes(num_nodes)
    
    # Wait for nodes to be ready
    wait_for_nodes_to_be_ready()
    
    # Start the Flask app
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting proxy server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False) 