import os
import sys
import threading
import subprocess
import time
from flask import Flask, request, Response
import requests

app = Flask(__name__)

def create_node_prefix(node_id):
    """Create a URL prefix for a node"""
    return f"/node{node_id}"

# Store references to each node's process
node_processes = {}

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
        # Forward the request to the node's port
        method = request.method
        url = f"http://localhost:{8000 + node_id}/{subpath}"
        
        # Get the data and headers from the original request
        headers = {k: v for k, v in request.headers if k != 'Host'}
        data = request.get_data()
        
        # Make the request to the internal node
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=data,
            params=request.args
        )
        
        # Return the response from the node
        return Response(
            response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )
    except Exception as e:
        return f"Error proxying request to Node {node_id}: {str(e)}", 500

if __name__ == "__main__":
    # Get the node ID
    if len(sys.argv) > 1:
        try:
            node_id = int(sys.argv[1])
            node_processes[node_id] = None
            print(f"Starting proxy for Node {node_id}")
        except ValueError:
            print("Invalid node ID. Must be an integer.")
            sys.exit(1)
    else:
        # If no node ID provided, run as a proxy for all nodes
        for i in range(3):  # Default to 3 nodes
            node_processes[i] = None
        print("Starting proxy for all nodes")
    
    # Start the Flask app
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False) 