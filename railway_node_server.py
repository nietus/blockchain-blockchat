import os
import sys
import threading
import subprocess
import time
import signal
import socket
from flask import Flask, request, Response
import requests
from flask_cors import CORS

app = Flask(__name__)
# Enable CORS for all routes and origins
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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
    time.sleep(10)  # Increased from 5 to 10 seconds
    
    # Bootstrap connection string for other nodes
    host = socket.gethostname()
    bootstrap_connection = f"{host}:{first_kademlia_port}"
    
    # Start additional nodes
    for i in range(1, num_nodes):
        http_port = first_http_port + i
        kademlia_port = first_kademlia_port + i
        
        node_process = start_node(i, http_port, kademlia_port, bootstrap_connection)
        node_processes[i] = node_process
        
        # Give each node time to start up and sync
        time.sleep(5)  # Increased from 2 to 5 seconds
    
    print(f"Started {num_nodes} blockchain nodes")
    
    # Allow extra time for initial chain synchronization
    print("Allowing extra time for initial chain synchronization...")
    time.sleep(10)

@app.route('/', methods=['GET'])
def home():
    """Root endpoint showing status of all nodes"""
    nodes_info = ""
    for node_id in node_processes:
        prefix = create_node_prefix(node_id)
        nodes_info += f"<li><a href='{prefix}/chain'>Node {node_id} - View Blockchain</a> | <a href='{prefix}/sync_chain'>Sync Chain</a></li>"
    
    return f"""
    <html>
    <head>
        <title>Multi-Node Blockchain</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #333; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ margin-bottom: 10px; }}
            a {{ color: #0066cc; text-decoration: none; margin-right: 10px; }}
            a:hover {{ text-decoration: underline; }}
            .actions {{ margin-top: 20px; }}
        </style>
    </head>
    <body>
        <h1>Multi-Node Blockchain Network</h1>
        <p>This is a multi-node blockchain network running on Railway.</p>
        <h2>Available Nodes:</h2>
        <ul>
            {nodes_info}
        </ul>
        <div class="actions">
            <h2>Network Actions:</h2>
            <p>
                <a href="/chain">View Default Chain</a> | 
                <a href="/sync_all_chains">Sync All Chains</a> | 
                <a href="/chain_status">View Chain Status</a>
            </p>
        </div>
    </body>
    </html>
    """

@app.route('/node<int:node_id>/', defaults={'subpath': ''}, methods=['GET', 'POST', 'PUT', 'DELETE'])
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
        
        # Forward directly to the node's endpoint
        # Remove trailing slash to avoid double-slash issues
        if subpath:
            url = f"http://127.0.0.1:{http_port}/{subpath}"
        else:
            # Root path case
            url = f"http://127.0.0.1:{http_port}/"
        
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

@app.route('/chain', methods=['GET'])
def get_default_chain():
    """Redirect root-level chain requests to node0's chain for convenience"""
    return proxy_to_node(0, "chain")

@app.route('/mine', methods=['GET'])
def get_default_mine():
    """Redirect root-level mine requests to node0 for convenience"""
    return proxy_to_node(0, "mine")

@app.route('/new_transaction', methods=['POST'])
def post_default_transaction():
    """Redirect root-level transaction requests to node0 for convenience"""
    return proxy_to_node(0, "new_transaction")

@app.route('/sync_chain', methods=['GET'])
def get_default_sync_chain():
    """Redirect root-level sync_chain requests to node0 for convenience"""
    return proxy_to_node(0, "sync_chain")

@app.route('/sync_all_chains', methods=['GET'])
def sync_all_chains():
    """Trigger synchronization on all nodes"""
    results = []
    
    for node_id in node_processes:
        try:
            http_port = 8000 + node_id
            response = requests.get(f"http://127.0.0.1:{http_port}/sync_chain", timeout=5)
            results.append(f"Node {node_id}: {response.status_code} - {response.text}")
        except Exception as e:
            results.append(f"Node {node_id}: Error - {str(e)}")
    
    return f"""
    <html>
    <head>
        <title>Chain Synchronization Results</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #333; }}
            pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 5px; }}
            a {{ color: #0066cc; text-decoration: none; }}
        </style>
    </head>
    <body>
        <h1>Chain Synchronization Results</h1>
        <pre>{chr(10).join(results)}</pre>
        <p><a href="/">Back to Home</a> | <a href="/chain_status">View Chain Status</a></p>
    </body>
    </html>
    """

@app.route('/chain_status', methods=['GET'])
def chain_status():
    """Show status of all chains"""
    node_info = []
    
    for node_id in node_processes:
        try:
            http_port = 8000 + node_id
            response = requests.get(f"http://127.0.0.1:{http_port}/chain", timeout=5)
            if response.status_code == 200:
                data = response.json()
                chain_length = data.get('length', 0)
                chain_hash = "None"
                if data.get('chain') and len(data['chain']) > 0:
                    chain_hash = data['chain'][-1].get('hash', 'Unknown')[:10]
                node_info.append({
                    'id': node_id,
                    'length': chain_length,
                    'latest_hash': chain_hash,
                    'status': 'Online'
                })
            else:
                node_info.append({
                    'id': node_id,
                    'length': 'N/A',
                    'latest_hash': 'N/A',
                    'status': f'Error {response.status_code}'
                })
        except Exception as e:
            node_info.append({
                'id': node_id,
                'length': 'N/A',
                'latest_hash': 'N/A',
                'status': f'Error: {str(e)}'
            })
    
    # Create HTML table
    table_rows = ""
    for node in node_info:
        table_rows += f"""
        <tr>
            <td>{node['id']}</td>
            <td>{node['length']}</td>
            <td>{node['latest_hash']}</td>
            <td>{node['status']}</td>
            <td><a href="/node{node['id']}/chain">View Chain</a> | <a href="/node{node['id']}/sync_chain">Sync Chain</a></td>
        </tr>
        """
    
    return f"""
    <html>
    <head>
        <title>Blockchain Network Status</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #333; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            tr:hover {{ background-color: #e9e9e9; }}
            .actions {{ margin-top: 20px; }}
            a {{ color: #0066cc; text-decoration: none; margin-right: 10px; }}
            a:hover {{ text-decoration: underline; }}
            .refresh {{ background-color: #4CAF50; color: white; padding: 10px 15px; border: none; 
                      border-radius: 4px; cursor: pointer; margin-top: 20px; }}
            .refresh:hover {{ background-color: #45a049; }}
        </style>
        <meta http-equiv="refresh" content="10">
    </head>
    <body>
        <h1>Blockchain Network Status</h1>
        <p>This page auto-refreshes every 10 seconds to show the current state of all nodes.</p>
        
        <table>
            <tr>
                <th>Node ID</th>
                <th>Chain Length</th>
                <th>Latest Block Hash</th>
                <th>Status</th>
                <th>Actions</th>
            </tr>
            {table_rows}
        </table>
        
        <div class="actions">
            <a href="/">Back to Home</a> | 
            <a href="/sync_all_chains">Sync All Chains</a> | 
            <a href="/chain_status">Refresh Now</a>
        </div>
    </body>
    </html>
    """

def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    print("Shutting down all nodes...")
    for node_id, process in node_processes.items():
        if process:
            process.terminate()
    sys.exit(0)

def wait_for_nodes_to_be_ready(timeout=90):  # Increased timeout from 60 to 90 seconds
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
                # Try to connect to the node's root endpoint
                # This works with the Flask blueprint routing
                response = requests.get(f"http://127.0.0.1:{http_port}/", timeout=1)
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
        
        # Add an explicit call to check node chain consistency
        print("Initiating chain synchronization check for all nodes...")
        for node_id in range(1, len(node_processes)):
            try:
                # Request consensus check on each non-bootstrap node
                http_port = 8000 + node_id
                response = requests.get(f"http://127.0.0.1:{http_port}/sync_chain", timeout=5)
                print(f"Node {node_id} chain sync initiated: {response.status_code}")
            except Exception as e:
                print(f"Error initiating chain sync for node {node_id}: {e}")
        
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