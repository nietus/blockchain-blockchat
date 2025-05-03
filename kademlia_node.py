import asyncio
import json
import random
import sys
import socket
import os
import threading
import time
from kademlia.network import Server
from kademlia.utils import digest

class KademliaNode:
    def __init__(self, port=5678, bootstrap_nodes=None, http_address=None):
        """
        Initialize a Kademlia node
        
        Args:
            port (int): Port to listen on
            bootstrap_nodes (list): List of (host, port) tuples for bootstrap nodes
            http_address (str): HTTP address of the associated blockchain node
        """
        self.port = port
        self.bootstrap_nodes = bootstrap_nodes or []
        self.server = Server()
        # Use a stable node_id if possible, maybe derived from http_address or persisted
        # For simplicity, keeping random for now, but consider persistence
        self.node_id = digest(random.getrandbits(255).to_bytes(32, byteorder='big'))
        self.loop = asyncio.get_event_loop()
        if self.loop.is_closed():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        self.running = False
        # Store the HTTP address of the associated blockchain node
        self.http_address = http_address or f'http://{self.get_ip()}:{os.environ.get("FLASK_RUN_PORT", 8000)}' # Fallback
        self.dht_key = "blockchain_nodes_v2" # Use a distinct key
        
    async def start(self):
        """Start the Kademlia server and join the network"""
        if self.running:
            print(f"Kademlia DHT already running on port {self.port}")
            return
            
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_socket.bind(('0.0.0.0', self.port))
            test_socket.close()
        except OSError as e:
            if e.errno == 98:
                print(f"Port {self.port} is already in use. Assuming existing instance.")
                # Maybe try to connect to the existing instance?
                # For now, we just won't start a new server.
                self.running = False # Indicate we didn't start it
                return
            raise
            
        await self.server.listen(self.port)
        self.running = True
        print(f"Kademlia DHT node listening on port {self.port}")
        
        if self.bootstrap_nodes:
            print(f"Bootstrapping with nodes: {self.bootstrap_nodes}")
            # Use ensure_future for non-blocking bootstrap
            tasks = [self.server.bootstrap([(host, port)]) for host, port in self.bootstrap_nodes]
            await asyncio.gather(*tasks)
            print("Bootstrap process initiated.")
        
        # Store richer node information
        self.node_info = {
            "kad_host": self.get_ip(),
            "kad_port": self.port,
            "http_address": self.http_address,
            "node_id": self.node_id.hex(), # Use hex for JSON compatibility
            "timestamp": asyncio.get_event_loop().time()
        }
        # Register asynchronously
        asyncio.ensure_future(self.register_self())
        print("Node registration scheduled.")
    
    async def register_self(self):
        """Register this node in the DHT under a specific key"""
        if not self.running:
            print("Cannot register node - Kademlia DHT not running or failed to start")
            return
            
        # Update timestamp before registering
        self.node_info['timestamp'] = asyncio.get_event_loop().time()

        try:
            print(f"Attempting to register/update node info in DHT: {self.node_info}")
            
            # First, ensure we're bootstrapped if possible
            if self.bootstrap_nodes and hasattr(self.server, 'bootstrap'):
                # Try re-bootstrapping to find more peers if we don't have many
                if len(self.server.protocol.router.getNodes()) < 3:
                    print("Re-bootstrapping to find more peers before registering")
                    for host, port in self.bootstrap_nodes:
                        await self.server.bootstrap([(host, port)])
            
            # Wait a moment for bootstrap to have an effect
            await asyncio.sleep(0.5)
            
            # Store using both our node_id and a well-known key
            common_key = "blockchain_nodes_registry"
            
            # First store using our node ID
            await self.server.set(self.node_id.hex(), json.dumps(self.node_info))
            print(f"Successfully registered node {self.node_id.hex()} in the DHT.")
            
            # If we're bootstrapped and have neighbors, also store under the common key
            if len(self.server.protocol.router.getNodes()) > 0:
                # Try to read the existing registry first
                try:
                    registry_value = await self.server.get(common_key)
                    if registry_value:
                        registry = json.loads(registry_value)
                    else:
                        registry = {}
                except Exception:
                    registry = {}
                
                if not isinstance(registry, dict):
                    registry = {}
                
                # Add our node to the registry
                registry[self.node_id.hex()] = self.node_info
                
                # Store the updated registry
                await self.server.set(common_key, json.dumps(registry))
                print(f"Added node to common registry: {self.node_id.hex()}")
            else:
                print("No neighbors in routing table to store common registry")
                
        except Exception as e:
             print(f"Error registering node {self.node_id.hex()} in DHT: {e}")
             import traceback
             traceback.print_exc()
    
    async def get_active_blockchain_peers(self, timeout_seconds=300):
        """Get HTTP addresses of active blockchain peers discovered via Kademlia."""
        if not self.running:
            print("Cannot get peers - Kademlia DHT not running")
            return []

        print("Refreshing peer list via Kademlia...")
        
        peers = set()
        try:
            # Include self initially
            potential_node_ids = {self.node_id.hex()} 
            
            # First try to get the common registry which should have all nodes
            common_key = "blockchain_nodes_registry"
            try:
                registry_value = await self.server.get(common_key)
                if registry_value:
                    try:
                        registry = json.loads(registry_value)
                        if isinstance(registry, dict):
                            print(f"Found {len(registry)} nodes in common registry")
                            for node_id, node_data in registry.items():
                                if node_id != self.node_id.hex():  # Skip self
                                    potential_node_ids.add(node_id)
                                    try:
                                        # Process node from registry directly
                                        if isinstance(node_data, dict):
                                            print(f"Processing node from registry: {node_id}")
                                            http_address = node_data.get('http_address')
                                            
                                            # Validate and clean the HTTP address
                                            if http_address:
                                                # Add scheme if missing
                                                if not http_address.startswith(('http://', 'https://')):
                                                    if 'railway.app' in http_address:
                                                        http_address = f"https://{http_address}"
                                                    else:
                                                        http_address = f"http://{http_address}"
                                                    print(f"Added scheme to registry URL: {http_address}")
                                                
                                                # Remove any semicolons
                                                http_address = http_address.replace(';', '')
                                                
                                                # For Railway apps, ensure node prefix is included
                                                if 'railway.app' in http_address and '/node' not in http_address:
                                                    # Try to get node ID from port offset
                                                    if 'kad_port' in node_data:
                                                        base_port = 5678
                                                        port_offset = node_data['kad_port'] - base_port
                                                        if port_offset >= 0:
                                                            http_address = f"{http_address}/node{port_offset}"
                                                            
                                                # Add the peer if it's valid
                                                print(f"Adding peer from registry: {http_address}")
                                                peers.add(http_address)
                                    except Exception as e:
                                        print(f"Error processing registry node {node_id}: {e}")
                    except json.JSONDecodeError:
                        print(f"Could not decode registry JSON: {registry_value}")
            except Exception as e:
                print(f"Error fetching common registry: {e}")
                
            # Access the routing table buckets directly
            if hasattr(self.server, 'protocol') and hasattr(self.server.protocol, 'router'):
                # Iterate through all buckets in the routing table
                for bucket in self.server.protocol.router.buckets:
                    for node in bucket.nodes:
                        # Handle different node types safely
                        try:
                            # If node is already a node object with id attribute
                            if hasattr(node, 'id'):
                                if node.id:
                                    potential_node_ids.add(node.id.hex())
                            # If node is a raw bytes object (node ID)
                            elif isinstance(node, bytes):
                                potential_node_ids.add(node.hex())
                            # If node is a tuple with the node ID as first element
                            elif isinstance(node, tuple) and len(node) > 0 and isinstance(node[0], bytes):
                                potential_node_ids.add(node[0].hex())
                        except Exception as e:
                            print(f"Error processing node in bucket: {e}, node type: {type(node)}")
                            continue  # Skip this node and continue with others
                
                print(f"Found {len(potential_node_ids)} potential node IDs in routing table. Fetching details...")

                tasks = [self.server.get(node_id) for node_id in potential_node_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                current_time = asyncio.get_event_loop().time()
                for i, result in enumerate(results):
                    node_id = list(potential_node_ids)[i]
                    if isinstance(result, Exception) or result is None:
                        print(f"Could not retrieve data for node {node_id}: {result}")
                        continue
                    try:
                        node_data = json.loads(result)
                        print(f"Retrieved node data for {node_id}: {node_data}")
                        
                        # Check timestamp for freshness
                        if current_time - node_data.get('timestamp', 0) < timeout_seconds:
                            http_address = node_data.get('http_address')
                            if http_address:
                                if node_data.get('node_id') == self.node_id.hex():
                                    print(f"Skipping self node {node_id}")
                                    continue
                                    
                                # Special handling for Railway deployment with shared URL 
                                # but different node prefixes
                                if 'railway.app' in http_address:
                                    # Add scheme if missing
                                    if not http_address.startswith(('http://', 'https://')):
                                        http_address = f"https://{http_address}"
                                        print(f"Added https scheme to Railway URL: {http_address}")
                                    
                                    # Remove any semicolons that might be in the URL
                                    http_address = http_address.replace(';', '')
                                    
                                    # If there's already a node prefix, use it
                                    if '/node' in http_address and not http_address.endswith('/'):
                                        print(f"Adding Railway peer with prefixed address: {http_address}")
                                        peers.add(http_address)
                                    else:
                                        # Try to extract node ID from Kademlia data
                                        if 'kad_port' in node_data:
                                            # Calculate node number from port offset
                                            base_port = 5678
                                            port_offset = node_data['kad_port'] - base_port
                                            if port_offset >= 0:
                                                # Assuming node0 is on base port, node1 on base+1, etc.
                                                node_url = f"{http_address}/node{port_offset}"
                                                print(f"Adding derived Railway peer address: {node_url}")
                                                peers.add(node_url)
                                            else:
                                                print(f"Adding standard peer: {http_address}")
                                                peers.add(http_address)
                                        else:
                                            print(f"Adding standard peer: {http_address}")
                                            peers.add(http_address)
                                else:
                                    print(f"Adding peer with HTTP address: {http_address}")
                                    peers.add(http_address)
                            else:
                                print(f"Skipping node {node_id}: missing HTTP address")
                        else:
                            timestamp = node_data.get('timestamp', 0)
                            age = current_time - timestamp
                            print(f"Node {node_id} data is stale: age={age}s, timeout={timeout_seconds}s")

                    except json.JSONDecodeError:
                        print(f"Could not decode JSON for node {node_id}: {result}")
                    except Exception as e:
                        print(f"Error processing data for node {node_id}: {e}")

            # For Railway deployment, try direct node-prefix approach
            if 'railway.app' in self.http_address:
                base_url = self.http_address
                
                # Add scheme if missing
                if not base_url.startswith(('http://', 'https://')):
                    base_url = f"https://{base_url}"
                    print(f"Added https scheme to base URL: {base_url}")
                
                # Remove any semicolons that might be in the URL
                base_url = base_url.replace(';', '')
                
                # Strip any existing node prefix
                if '/node' in base_url:
                    base_url = base_url.split('/node')[0]
                # Add paths for potential sibling nodes
                for node_id in range(5):  # Try node0 through node4
                    node_url = f"{base_url}/node{node_id}"
                    # Don't add if it's our own address or already in the list
                    if node_url != self.http_address and node_url not in peers:
                        print(f"Adding potential Railway node by convention: {node_url}")
                        peers.add(node_url)

            # Add direct querying for nodes we know might be in the network
            # This can help if the routing table doesn't have complete info
            for port_offset in range(5):  # Try a few potential ports
                try:
                    ip = self.get_ip()
                    test_port = 5678 + port_offset  # Common Kademlia ports
                    
                    # Skip our own port
                    if test_port == self.port:
                        continue
                        
                    print(f"Directly probing potential node at {ip}:{test_port}")
                    node = (ip, test_port)
                    
                    # Try different ping approaches based on kademlia library version
                    try:
                        # Most reliable: check if we can send a find_node query 
                        # which works across more kademlia implementations
                        find_id = digest(random.getrandbits(255).to_bytes(32, byteorder='big'))
                        find_future = self.server.protocol.callFindNode(node, find_id)
                        result = await asyncio.wait_for(find_future, timeout=2)
                        if result and isinstance(result, list):
                            print(f"Found active node at {ip}:{test_port} via find_node query")
                            
                            # Construct standard HTTP address format
                            http_port = 8000 + port_offset  # Convention: HTTP port = 8000 + offset
                            http_address = f"http://{ip}:{http_port}"
                            if http_address != self.http_address:  # Don't add self
                                print(f"Adding discovered peer via find_node: {http_address}")
                                peers.add(http_address)
                    except Exception as e:
                        print(f"Find_node probe failed: {e}, trying simpler approach")
                        # Try simplest approach possible
                        try:
                            # Check if node exists in the routing table
                            if self.server.protocol.router.isNewNode(node):
                                print(f"Node {ip}:{test_port} is not in routing table")
                            else:
                                print(f"Found known node at {ip}:{test_port}")
                                # Construct standard HTTP address format
                                http_port = 8000 + port_offset
                                http_address = f"http://{ip}:{http_port}"
                                if http_address != self.http_address:
                                    print(f"Adding discovered peer via routing table: {http_address}")
                                    peers.add(http_address)
                        except Exception as e2:
                            print(f"Routing table check failed: {e2}")
                            pass
                except Exception as e:
                    # Expected to fail for nodes that don't exist, only print for unexpected errors
                    if not isinstance(e, (asyncio.TimeoutError, ConnectionRefusedError)):
                        print(f"Unexpected error probing {ip}:{test_port}: {e}")
                        # Don't re-raise, just continue with next port

        except Exception as e:
            print(f"Error during Kademlia peer discovery: {e}")
            import traceback
            traceback.print_exc()

        print(f"Discovered active blockchain peers via Kademlia: {list(peers)}")
        return list(peers)
    
    def get_ip(self):
        """Get the local IP address usable within the Docker network."""
        # First try to get the hostname (works well in Docker)
        hostname = socket.gethostname()
        
        try:
            # Try to resolve hostname to IP address
            ip = socket.gethostbyname(hostname)
            # If this is localhost or loopback, try another approach
            if ip.startswith('127.') or ip == '::1':
                raise ValueError("Got loopback address")
            return ip
        except Exception:
            # Fallback: try to get IP by creating a socket connection
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Doesn't need to be reachable, just to determine interface IP
                s.connect(('8.8.8.8', 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                # Last resort: use the hostname (used in Docker internal networks)
                return hostname
    
    def run_in_thread(self):
        """Run the Kademlia node's asyncio loop in a separate thread."""
        if self.running:
            print("Kademlia run_in_thread called but already seems to be running.")
            return
            
        def start_loop():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.start())
                if self.running: # Check if start() succeeded
                     # Schedule periodic registration update
                     async def periodic_register():
                         while self.running:
                             await self.register_self()
                             await asyncio.sleep(60) # Update registration every 60s
                     asyncio.ensure_future(periodic_register(), loop=self.loop)
                     self.loop.run_forever()
            except OSError as e:
                 if e.errno == 98:
                     print(f"Kademlia port {self.port} is already in use.")
                 else:
                     print(f"Error starting Kademlia event loop: {e}")
                     self.running = False
            except Exception as e:
                 print(f"Error in Kademlia event loop: {e}")
                 self.running = False
            finally:
                 print("Kademlia event loop finished.")
                 if not self.loop.is_closed():
                     self.loop.call_soon_threadsafe(self.loop.stop)
             
        thread = threading.Thread(target=start_loop, daemon=True)
        thread.start()
        # Give some time for the server to start listening
        time.sleep(1)
        print(f"Kademlia thread started. Running state: {self.running}")
        return thread
    
    def stop(self):
        """Stop the Kademlia node safely from another thread."""
        if self.running:
            print("Stopping Kademlia node...")
            self.running = False # Signal loops to stop
            if self.loop.is_running():
                 # Stop the server and the loop from the loop's thread
                 self.loop.call_soon_threadsafe(self.server.stop)
                 self.loop.call_soon_threadsafe(self.loop.stop)
            print("Kademlia DHT stop requested.")
        else:
             print("Kademlia node stop called, but not running.")

# Command line interface to run a standalone Kademlia node
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run a Kademlia DHT node")
    parser.add_argument('--port', type=int, default=5678, help='Port to listen on')
    parser.add_argument('--bootstrap', nargs='+', default=[], 
                        help='Bootstrap nodes in the format host:port')
    parser.add_argument('--http-addr', type=str, default=None, help='HTTP address of the associated blockchain node')
    
    args = parser.parse_args()
    
    # Parse bootstrap nodes
    bootstrap_nodes = []
    for node in args.bootstrap:
        try:
            host, port = node.split(':')
            bootstrap_nodes.append((host, int(port)))
        except ValueError:
            print(f"Invalid bootstrap node format: {node}. Should be host:port")
            sys.exit(1)
    
    # Create and run the node
    node = KademliaNode(port=args.port, bootstrap_nodes=bootstrap_nodes, http_address=args.http_addr)
    
    # Run in the main thread for standalone execution
    try:
        node.run_in_thread() # Start in thread
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        node.stop() 