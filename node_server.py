import os
import sys
import signal
import atexit
from hashlib import sha256
import json
import time
import threading
import asyncio
import logging
import socket
import queue

from flask import Flask, request, Blueprint
import requests
from kademlia_node import KademliaNode
from flask_cors import CORS


class Block:
    def __init__(self, index, transactions, timestamp, previous_hash, nonce=0):
        self.index = index
        self.transactions = transactions
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = None

    def compute_hash(self):
        temp_hash = self.hash
        self.hash = None
        block_string = json.dumps(self.__dict__, sort_keys=True)
        computed = sha256(block_string.encode()).hexdigest()
        self.hash = temp_hash
        return computed

    def to_dict(self):
        return {
            'index': self.index,
            'transactions': self.transactions,
            'timestamp': self.timestamp,
            'previous_hash': self.previous_hash,
            'nonce': self.nonce,
            'hash': self.hash
        }


class Blockchain:
    difficulty = 2

    def __init__(self, chain=None):
        self.unconfirmed_transactions = []
        self.chain = []
        if chain:
            self.chain = chain
        else:
            self.create_genesis_block()

    def create_genesis_block(self):
        genesis_block = Block(0, [], 0, "0")
        genesis_block.hash = self.proof_of_work(genesis_block)
        self.chain.append(genesis_block)
        logger.info("Genesis block created and mined.")

    @property
    def last_block(self):
        return self.chain[-1]

    def add_block(self, block, proof):
        previous_hash = self.last_block.hash
        if previous_hash != block.previous_hash:
            logger.error(f"Block {block.index} prev_hash {block.previous_hash} doesn't match last block hash {previous_hash}")
            return False
        if not self.is_valid_proof(block, proof):
            logger.error(f"Block {block.index} proof {proof} is invalid")
            return False

        block.hash = proof
        self.chain.append(block)
        logger.info(f"Added block {block.index} with hash {proof[:8]}...")
        return True

    @staticmethod
    def proof_of_work(block):
        block.nonce = 0
        computed_hash = block.compute_hash()
        while not computed_hash.startswith('0' * Blockchain.difficulty):
            block.nonce += 1
            computed_hash = block.compute_hash()
        return computed_hash

    def add_new_transaction(self, transaction):
        if not all(k in transaction for k in ('author', 'content', 'timestamp')):
            logger.warning(f"Transaction missing required fields: {transaction}")
            return False
        self.unconfirmed_transactions.append(transaction)
        logger.info(f"Added transaction: {transaction}")
        return True

    @classmethod
    def is_valid_proof(cls, block, block_hash):
        if not block_hash.startswith('0' * cls.difficulty):
            return False
        original_hash = block.hash
        block.hash = None
        computed = block.compute_hash()
        block.hash = original_hash
        return block_hash == computed

    @classmethod
    def check_chain_validity(cls, chain):
        previous_hash = "0"
        for i, block in enumerate(chain):
            if isinstance(block, dict):
                try:
                    block_obj = Block(block['index'], block['transactions'], block['timestamp'],
                                      block['previous_hash'], block['nonce'])
                    block_obj.hash = block['hash']
                except KeyError as e:
                    logger.error(f"Block data missing key {e} at index {i}")
                    return False
            elif isinstance(block, Block):
                block_obj = block
            else:
                logger.error(f"Invalid item in chain at index {i}: {block}")
                return False

            block_hash = block_obj.hash
            if block_hash is None:
                logger.error(f"Block {block_obj.index} is missing hash.")
                return False
            
            if not cls.is_valid_proof(block_obj, block_hash) or \
               (i > 0 and previous_hash != block_obj.previous_hash):
                logger.warning(f"Chain validity check failed at block {block_obj.index}.")
                return False
            previous_hash = block_hash
        return True

    def mine(self):
        if not self.unconfirmed_transactions:
            logger.info("No transactions to mine.")
            return False

        last_block = self.last_block
        new_block = Block(index=last_block.index + 1,
                          transactions=self.unconfirmed_transactions,
                          timestamp=time.time(),
                          previous_hash=last_block.hash)

        proof = self.proof_of_work(new_block)
        
        if self.add_block(new_block, proof):
            logger.info(f"Successfully mined and added block {new_block.index}")
            self.unconfirmed_transactions = []
            # Save the chain after mining a block
            save_chain()
            announce_new_block(new_block.to_dict())
            return new_block.index
        else:
            logger.error(f"Failed to add mined block {new_block.index}")
            return False


app = Flask(__name__)
# Set up CORS to allow requests from any origin
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Keep track of node prefix for informational purposes
node_prefix = os.environ.get('NODE_PREFIX', '')

# No blueprints - register all routes directly on app
bp = app

blockchain = None
kademlia_node = None
kademlia_thread = None

# Queue for signaling the mining thread
mining_queue = queue.Queue()
mining_active = threading.Event() # Event to signal if mining is in progress

# Handle Railway deployment URL
railway_url = 'blockchain-bc-production.up.railway.app'
port = os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 8000))

if railway_url:
    this_node_http_address = railway_url
else:
    this_node_http_address = os.environ.get('HTTP_NODE_ADDRESS', f'http://127.0.0.1:{port}')

data_file_path = os.environ.get('DATA_FILE', 'chain.json')

hostname = socket.gethostname()
logging.basicConfig(level=logging.INFO, 
                   format=f'%(asctime)s {hostname} [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def mine_worker():
    """Background worker thread to handle mining requests."""
    logger.info("Mining worker thread started.")
    while True:
        try:
            # Wait for a signal to start mining
            mining_queue.get() # Blocks until an item is available
            if not blockchain or not blockchain.unconfirmed_transactions:
                logger.info("Mining worker received signal, but no transactions to mine.")
                mining_queue.task_done()
                continue
                
            if mining_active.is_set():
                logger.info("Mining is already in progress.")
                mining_queue.task_done()
                continue

            logger.info("Mining worker starting proof-of-work...")
            mining_active.set() # Signal that mining is active
            try:
                result = blockchain.mine()
                if result is not False:
                    logger.info(f"Mining worker successfully mined block #{result}")
                else:
                    logger.info("Mining worker: mining returned False (no tx or failed add)")
            except Exception as e:
                logger.error(f"Error during background mining: {e}", exc_info=True)
            finally:
                mining_active.clear() # Signal that mining is finished
                mining_queue.task_done() # Mark the task as done

        except Exception as e:
            logger.error(f"Error in mining worker loop: {e}", exc_info=True)
            # Avoid busy-looping on error
            time.sleep(5)

def setup_and_run_kademlia():
    global kademlia_node, kademlia_thread
    if kademlia_node and kademlia_node.running:
        logger.info("Kademlia already initialized and running.")
        return
        
    kademlia_port = int(os.environ.get('KADEMLIA_PORT', 5678))
    kademlia_bootstrap_env = os.environ.get('KADEMLIA_BOOTSTRAP', '')
    bootstrap_nodes = []
    
    # Extract bootstrap nodes from environment
    if kademlia_bootstrap_env:
        for node_str in kademlia_bootstrap_env.split(','):
            if node_str.strip():
                try:
                    host, port_str = node_str.strip().split(':')
                    bootstrap_nodes.append((host, int(port_str)))
                    logger.info(f"Added bootstrap node: {host}:{port_str}")
                except ValueError:
                    logger.warning(f"Invalid bootstrap node format: {node_str}. Ignoring.")
    
    # If no bootstrap nodes from environment and we're not the first node, 
    # try some reasonable defaults based on common container patterns
    if not bootstrap_nodes and kademlia_port > 5678:  # Not the first node
        try:
            # Assume Docker or similar environment, try default port on container network
            hostname = socket.gethostname()
            # Try to use IP resolution
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            
            # Derive network prefix from our IP
            ip_parts = ip.split('.')
            network_prefix = '.'.join(ip_parts[:-1])
            
            # Try a few nodes in the same subnet with the bootstrap port
            for i in range(1, 5):
                test_ip = f"{network_prefix}.{i}"
                # Skip if it's our own IP
                if test_ip == ip:
                    continue
                logger.info(f"Adding default bootstrap node: {test_ip}:5678")
                bootstrap_nodes.append((test_ip, 5678))
                
            # Also add the hostname of the node0 container
            if 'railway.app' in this_node_http_address:
                container_name = f"container_{'_'.join(this_node_http_address.replace('https://', '').replace('http://', '').split('/')[0].split('.'))}_0"
                logger.info(f"Adding container hostname bootstrap node: {container_name}:5678")
                bootstrap_nodes.append((container_name, 5678))
                
            # And add the hostname itself
            logger.info(f"Adding hostname bootstrap node: {hostname}:5678")
            bootstrap_nodes.append((hostname, 5678))
                
        except Exception as e:
            logger.error(f"Error setting up default bootstrap nodes: {e}")

    # Get the real HTTP address
    if '127.0.0.1' in this_node_http_address or 'localhost' in this_node_http_address:
        # Try to get a better IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            
            # Extract the port from the existing address
            port = this_node_http_address.split(':')[-1]
            # Create a new address with the real IP
            real_http_address = f"http://{ip}:{port}"
            logger.info(f"Using real IP address for HTTP: {real_http_address} (was {this_node_http_address})")
        except Exception as e:
            logger.error(f"Error determining real IP: {e}")
            real_http_address = this_node_http_address
    else:
        real_http_address = this_node_http_address

    logger.info(f"Initializing Kademlia DHT on port {kademlia_port} with bootstrap nodes: {bootstrap_nodes}")
    try:
        kademlia_node = KademliaNode(port=kademlia_port, 
                                   bootstrap_nodes=bootstrap_nodes,
                                   http_address=real_http_address)
        kademlia_thread = kademlia_node.run_in_thread()
        if not kademlia_node.running:
             logger.error("Kademlia thread started but node failed to run (maybe port conflict?)")
        else:
             logger.info("Kademlia node started successfully in background thread.")
             
             # Force an initial peer refresh after startup
             def delayed_peer_refresh():
                time.sleep(5)  # Wait for network to stabilize
                try:
                    # Force registration refresh
                    if kademlia_node.running and kademlia_node.loop.is_running():
                        logger.info("Forcing initial peer registration refresh")
                        asyncio.run_coroutine_threadsafe(kademlia_node.register_self(), kademlia_node.loop)
                except Exception as e:
                    logger.error(f"Error in delayed peer refresh: {e}")
                    
             threading.Thread(target=delayed_peer_refresh, daemon=True).start()
             
    except Exception as e:
        logger.error(f"Failed to initialize or run Kademlia node: {e}", exc_info=True)
        kademlia_node = None

def ensure_data_directory():
    data_dir = os.path.dirname(data_file_path)
    if data_dir and not os.path.exists(data_dir):
        logger.info(f"Creating data directory: {data_dir}")
        try:
             os.makedirs(data_dir)
        except OSError as e:
             logger.error(f"Failed to create data directory {data_dir}: {e}")

def save_chain():
    if blockchain:
        logger.info(f"Saving blockchain to {data_file_path}...")
        ensure_data_directory()
        chain_data = [block.to_dict() for block in blockchain.chain]
        try:
            with open(data_file_path, 'w') as f:
                json.dump(chain_data, f, indent=4)
            logger.info("Blockchain saved successfully.")
        except IOError as e:
            logger.error(f"Error saving blockchain: {e}")
    else:
        logger.warning("Save attempt failed: Blockchain not initialized.")

def load_chain():
    global blockchain
    ensure_data_directory()
    loaded_chain_data = None
    if os.path.exists(data_file_path):
        logger.info(f"Loading blockchain from {data_file_path}...")
        try:
            with open(data_file_path, 'r') as f:
                loaded_chain_data = json.load(f)
            logger.info("Blockchain data loaded.")
            if not isinstance(loaded_chain_data, list) or not all(isinstance(b, dict) for b in loaded_chain_data):
                 logger.error("Invalid chain data format in file. Starting fresh.")
                 loaded_chain_data = None 
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error loading blockchain: {e}. Starting fresh.")
            loaded_chain_data = None
            
    if loaded_chain_data:
        chain_objects = []
        valid_load = True
        try:
            for block_data in loaded_chain_data:
                 if not all(k in block_data for k in ('index', 'transactions', 'timestamp', 'previous_hash', 'nonce', 'hash')):
                      logger.error(f"Block data missing keys: {block_data}")
                      valid_load = False
                      break
                 block = Block(block_data['index'], block_data['transactions'], block_data['timestamp'], 
                               block_data['previous_hash'], block_data['nonce'])
                 block.hash = block_data['hash']
                 chain_objects.append(block)
            
            if valid_load and Blockchain.check_chain_validity(chain_objects):
                logger.info("Loaded blockchain is valid.")
                blockchain = Blockchain(chain=chain_objects) 
            else:
                 logger.error("Loaded blockchain is invalid. Starting fresh.")
                 blockchain = Blockchain() 
        except Exception as e:
             logger.error(f"Error recreating blocks from loaded data: {e}. Starting fresh.", exc_info=True)
             blockchain = Blockchain()
    else:
        logger.info("No saved blockchain found or load failed. Creating genesis block.")
        blockchain = Blockchain()
    
    # Schedule initial consensus check to sync with network after startup
    if kademlia_node and kademlia_node.running:
        logger.info("Scheduling initial blockchain consensus to sync with network after startup")
        def schedule_initial_consensus():
            time.sleep(10)  # Wait for kademlia to discover peers
            if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(consensus(), kademlia_node.loop)
                    logger.info("Initial consensus check scheduled successfully")
                except Exception as e:
                    logger.error(f"Failed to schedule initial consensus: {e}")
        
        threading.Thread(target=schedule_initial_consensus, daemon=True).start()

def graceful_shutdown():
     logger.info("Initiating graceful shutdown...")
     save_chain() 
     if kademlia_node:
          kademlia_node.stop()
     logger.info("Shutdown complete.")

atexit.register(graceful_shutdown)

@bp.route('/', methods=['GET'])
@bp.route('/node<int:node_id>/', methods=['GET'])
def home():
    """Home endpoint for health checks"""
    if not blockchain:
        return "Blockchain not initialized", 500
    return f"Blockchain node is running. Chain length: {len(blockchain.chain)}", 200

@bp.route('/new_transaction', methods=['POST'])
@bp.route('/new_transaction/', methods=['POST'])
@bp.route('/node<int:node_id>/new_transaction', methods=['POST'])
@bp.route('/node<int:node_id>/new_transaction/', methods=['POST'])
def new_transaction():
    if not blockchain:
         return "Blockchain not initialized", 500
    tx_data = request.get_json()
    if not tx_data:
        return "Invalid data", 400

    required_fields = ["author", "content"]
    if not all(field in tx_data for field in required_fields):
        return "Missing values", 400

    # Always set a fresh timestamp in milliseconds for better precision
    tx_data["timestamp"] = int(time.time() * 1000)  # Use milliseconds timestamp
    
    if blockchain.add_new_transaction(tx_data):
        return "Transaction submission successful", 201
    else:
         return "Invalid transaction data", 400

@bp.route('/chain', methods=['GET'])
@bp.route('/chain/', methods=['GET'])
@bp.route('/node<int:node_id>/chain', methods=['GET'])
@bp.route('/node<int:node_id>/chain/', methods=['GET'])
def get_chain():
    if not blockchain:
         return "Blockchain not initialized", 500
    
    # Remove the blocking verification logic
    # Consistency is handled by background consensus tasks
    # should_verify = request.args.get('verify', 'false').lower() == 'true'
    # if should_verify and kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
    #    ...
    
    logger.info("Returning current blockchain state.")
    chain_data = [block.to_dict() for block in blockchain.chain]
    active_peers = get_http_peers() # This still has a small timeout, might need optimization later
    return json.dumps({"length": len(chain_data),
                       "chain": chain_data,
                       "peers": list(active_peers)})
                       # "verified": should_verify})

@bp.route('/mine', methods=['GET'])
@bp.route('/mine/', methods=['GET'])
@bp.route('/node<int:node_id>/mine', methods=['GET'])
@bp.route('/node<int:node_id>/mine/', methods=['GET'])
def mine_unconfirmed_transactions():
    if not blockchain:
         return "Blockchain not initialized", 500
         
    # Check if mining is already in progress
    if mining_active.is_set():
        return "Mining is already in progress", 429 # 429 Too Many Requests
        
    # Check if there are transactions to mine
    if not blockchain.unconfirmed_transactions:
        return "No transactions to mine", 200
        
    # Signal the background worker thread to start mining
    logger.info("Received /mine request, signaling background worker...")
    try:
        # Add item to queue to trigger worker. Put non-blocking to avoid waiting if queue is full (shouldn't happen)
        mining_queue.put_nowait(True) 
        return "Mining process scheduled", 202 # 202 Accepted
    except queue.Full:
        logger.warning("Mining queue is full, cannot schedule mining now.")
        return "Mining worker busy, try again later", 503 # 503 Service Unavailable
    except Exception as e:
        logger.error(f"Error signaling mining worker: {e}")
        return "Error scheduling mining", 500

async def get_active_peers_async():
     if kademlia_node and kademlia_node.running:
          try:
               return await kademlia_node.get_active_blockchain_peers()
          except Exception as e:
               logger.error(f"Error calling Kademlia get_active_blockchain_peers: {e}")
               return []
     else:
          logger.warning("Kademlia node not running, cannot get active peers.")
          return []

def get_http_peers():
    if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(get_active_peers_async(), kademlia_node.loop)
            peer_list = future.result(timeout=5)
            peers = set(p for p in peer_list if p != this_node_http_address) 
            return peers
        except asyncio.TimeoutError:
             logger.error("Timeout getting peers from Kademlia.")
             return set()
        except Exception as e:
            logger.error(f"Error getting peers from Kademlia thread: {e}", exc_info=False)
            return set()
    else:
        return set()

@bp.route('/register_node', methods=['POST'])
def register_new_peers():
    logger.info("Received manual peer registration request (less relevant with Kademlia).")
    nodes = request.get_json().get('nodes')
    if nodes:
        pass 
    return "Kademlia handles dynamic discovery.", 200

@bp.route('/register_with', methods=['POST'])
def register_with_existing_node():
    node_address = request.get_json().get("node_address")
    logger.info(f"Received registration request from {node_address} (less relevant with Kademlia).")
    return "Registration acknowledged (Kademlia handles discovery)", 200

@bp.route('/add_block', methods=['POST'])
def verify_and_add_block():
    if not blockchain:
         return "Blockchain not initialized", 500
    block_data = request.get_json()
    if not block_data:
        return "Invalid data", 400

    try:
        required_keys = ('index', 'transactions', 'timestamp', 'previous_hash', 'nonce', 'hash')
        if not all(k in block_data for k in required_keys):
             logger.warning(f"Received block data missing keys: {block_data}")
             return "Invalid block data received", 400

        # Check if we already have this block by hash
        if any(b.index == block_data['index'] and b.hash == block_data['hash'] for b in blockchain.chain):
             logger.info(f"Block #{block_data['index']} with hash {block_data['hash'][:8]}... already exists. Ignoring.")
             return "Block already exists", 200
             
        last_block = blockchain.last_block
        
        # Case 1: Block connects directly to our chain
        if block_data['previous_hash'] == last_block.hash and block_data['index'] == last_block.index + 1:
            logger.info(f"Received block #{block_data['index']} connects directly to our chain. Adding...")
            block = Block(block_data['index'], block_data['transactions'], block_data['timestamp'],
                          block_data['previous_hash'], block_data['nonce'])
            if blockchain.add_block(block, block_data['hash']):
                 logger.info(f"Successfully added block #{block.index} with hash {block_data['hash'][:8]}... to chain")
                 save_chain()  # Save chain after successful addition
                 return "Block added to the chain", 201
            else:
                 logger.warning(f"Received block #{block.index} failed validation")
                 return "Block rejected by node (validation failed)", 400
        
        # Case 2: We're behind - the new block builds on something we don't have
        elif block_data['index'] > last_block.index + 1:
            logger.warning(f"Received block #{block_data['index']} but we're at #{last_block.index}. We're behind.")
            # We've missed some blocks, schedule a sync
            if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                logger.info("Scheduling background consensus due to received advanced block")
                # Schedule consensus() to run in the Kademlia event loop without waiting
                kademlia_node.loop.call_soon_threadsafe(asyncio.ensure_future, consensus())
            else:
                logger.warning("Cannot schedule sync, Kademlia node not running")
            
            # Respond immediately that we've acknowledged the block and are syncing
            return "Block acknowledged, chain synchronization scheduled", 202
            
        # Case 3: Block is from a fork or alternative chain (same index but different content)
        elif block_data['index'] == last_block.index and block_data['hash'] != last_block.hash:
            logger.warning(f"Received block #{block_data['index']} appears to be from a fork. Triggering consensus.")
            # We might be on a fork, schedule a consensus check
            if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                logger.info("Scheduling background consensus due to potential fork")
                kademlia_node.loop.call_soon_threadsafe(asyncio.ensure_future, consensus())
            else:
                logger.warning("Cannot schedule consensus, Kademlia node not running")
                
            return "Block from potential fork received, consensus scheduled", 202
            
        # Case 4: Received an older block
        elif block_data['index'] < last_block.index:
            logger.info(f"Received block #{block_data['index']} which is older than our chain head #{last_block.index}")
            return "Block is older than current chain head", 200
        
        # Case 5: Received a block at same index but doesn't connect
        else:
            logger.warning(f"Received block #{block_data['index']} doesn't connect to our chain properly")
            return "Block doesn't connect to current chain", 400

    except Exception as e:
        logger.error(f"Error processing received block: {e}", exc_info=True)
        return "Internal server error processing block", 500

@bp.route('/pending_tx')
def get_pending_tx():
     if not blockchain:
          return "Blockchain not initialized", 500
     return json.dumps(blockchain.unconfirmed_transactions)

@bp.route('/sync_chain', methods=['GET'])
@bp.route('/sync_chain/', methods=['GET'])
@bp.route('/node<int:node_id>/sync_chain', methods=['GET'])
@bp.route('/node<int:node_id>/sync_chain/', methods=['GET'])
def sync_blockchain():
    """Explicitly trigger blockchain synchronization via consensus"""
    if not blockchain:
        return "Blockchain not initialized", 500
    
    if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
        try:
            logger.info("Scheduling background blockchain synchronization")
            # Schedule consensus() to run in the Kademlia event loop without waiting
            kademlia_node.loop.call_soon_threadsafe(asyncio.ensure_future, consensus())
            return "Blockchain synchronization scheduled", 202 # Return 202 Accepted
        except Exception as e:
            logger.error(f"Error scheduling background blockchain synchronization: {e}")
            return f"Error scheduling synchronization: {str(e)}", 500
    else:
        logger.error("Cannot sync blockchain: Kademlia node not running")
        return "Cannot sync - P2P network node not running", 500

async def consensus():
    global blockchain
    if not blockchain:
        logger.error("Consensus cannot run: Blockchain not initialized")
        return False
        
    logger.info("Running consensus check...")
    longest_chain = None
    current_len = len(blockchain.chain)
    max_len = current_len

    active_peers = await get_active_peers_async()
    
    # Clean up any malformed URLs in the peer list
    sanitized_peers = []
    for peer in active_peers:
        # Remove any semicolons
        clean_peer = peer.replace(';', '')
        # Ensure URL has a scheme
        if not clean_peer.startswith(('http://', 'https://')):
            if 'railway.app' in clean_peer:
                clean_peer = f"https://{clean_peer}"
            else:
                clean_peer = f"http://{clean_peer}"
        sanitized_peers.append(clean_peer)
    
    active_peers = sanitized_peers
    logger.info(f"Found {len(active_peers)} active peers via Kademlia for consensus: {active_peers}")
    
    if not active_peers:
        logger.warning("No peers available for consensus. Chain remains unchanged.")
        return False

    # Special case for Railway deployment - if we're running in Railway, 
    # check if we're the bootstrap node (node0)
    is_bootstrap_node = False
    if 'railway.app' in this_node_http_address and '/node0' in this_node_http_address:
        logger.info("This is the bootstrap node (node0) in Railway deployment")
        is_bootstrap_node = True

    tasks = []
    for node in active_peers:
         if node == this_node_http_address: continue
         logger.info(f"Adding task to fetch chain from peer: {node}")
         tasks.append(fetch_chain_from_peer(node))
    
    if not tasks:
        logger.warning("No valid peer tasks created for consensus")
        return False
         
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_chains_count = 0
    error_count = 0
    for i, result in enumerate(results):
         peer_node = active_peers[i] if i < len(active_peers) else "unknown"
         if isinstance(result, Exception):
              logger.warning(f"Consensus error fetching chain from {peer_node}: {result}")
              error_count += 1
         elif result is None:
              logger.warning(f"Null result when fetching chain from {peer_node}")
         elif result:
              valid_chains_count += 1
              length, chain = result
              logger.info(f"Received valid chain from {peer_node} with length {length}")
              
              # Special handling for bootstrap node - prioritize its chain
              if is_bootstrap_node and '/node0' in peer_node:
                   logger.info(f"Found bootstrap node chain with length {length} - giving priority")
                   if blockchain.check_chain_validity(chain):
                        longest_chain = chain
                        max_len = length
                        break  # We've found the authoritative source - stop looking
                        
              # Normal consensus process
              if length > max_len and blockchain.check_chain_validity(chain):
                   logger.info(f"Longer valid chain found at {peer_node} (length {length} > {max_len})")
                   max_len = length
                   longest_chain = chain
    
    logger.info(f"Consensus summary: {valid_chains_count} valid chains, {error_count} errors, current length: {current_len}, max found: {max_len}")

    if longest_chain:
        blockchain.chain = longest_chain 
        logger.info(f"Consensus successful: Replaced local chain (length {current_len}) with new chain (length {max_len}).")
        save_chain()
        return True
    else:
        logger.info("Consensus check complete: Local chain remains authoritative.")
        return False

async def fetch_chain_from_peer(node_address):
     logger.info(f"Fetching chain from {node_address}...")
     
     # Ensure URL has a scheme
     if not node_address.startswith(('http://', 'https://')):
         # For Railway, use https
         if 'railway.app' in node_address:
             node_address = f"https://{node_address}"
         else:
             node_address = f"http://{node_address}"
         logger.info(f"Added scheme to URL: {node_address}")
     
     # Remove any semicolons that might be in the URL
     node_address = node_address.replace(';', '')
     
     # For Railway deployment with node paths, ensure URL is properly formed
     if '/node' in node_address:
         chain_url = f"{node_address}/chain" if not node_address.endswith('/') else f"{node_address}chain"
     else:
         chain_url = f"{node_address}/chain"
         
     logger.info(f"Using chain URL: {chain_url}")
     
     try:
          loop = asyncio.get_running_loop()
          # First try with a HEAD request to check if the node is responding at all
          try:
              head_response = await loop.run_in_executor(None, lambda: requests.head(
                  chain_url, 
                  timeout=3
              ))
              head_response.raise_for_status()
          except Exception as e:
              logger.warning(f"Node {node_address} not responding to HEAD request: {e}")
              return None
          
          # If HEAD request worked, proceed with full GET
          response = await loop.run_in_executor(None, lambda: requests.get(
              chain_url, 
              timeout=10
          ))
          response.raise_for_status() 
          data = response.json()
          length = data.get('length', 0)
          chain_dump = data.get('chain', [])
          
          if not chain_dump:
               logger.warning(f"Received empty chain from {node_address}")
               return None
          
          logger.info(f"Received chain data from {node_address} with {length} blocks")
          
          # Create Block objects for validation
          chain_objects = []
          try:
               for block_data in chain_dump:
                    block = Block(block_data['index'], block_data['transactions'], block_data['timestamp'],
                                 block_data['previous_hash'], block_data['nonce'])
                    block.hash = block_data['hash']
                    chain_objects.append(block)
                    
               if not chain_objects:
                    logger.warning(f"Failed to convert chain data from {node_address} to Block objects")
                    return None
                    
               # Check first block to make sure it's a genesis block
               if chain_objects[0].index != 0 or chain_objects[0].previous_hash != "0":
                    logger.warning(f"First block from {node_address} is not a valid genesis block")
                    return None
                    
               if Blockchain.check_chain_validity(chain_objects):
                    logger.info(f"Received valid chain of length {length} from {node_address}")
                    return length, chain_objects
               else:
                    logger.warning(f"Received invalid chain from {node_address}")
                    return None
          except KeyError as e:
               logger.error(f"Missing key in block data from {node_address}: {e}")
               return None
          except Exception as e:
               logger.error(f"Error processing chain data from {node_address}: {e}")
               return None
     except requests.exceptions.Timeout:
          logger.error(f"Timeout fetching chain from {node_address}")
          return None
     except requests.exceptions.ConnectionError:
          logger.error(f"Connection error fetching chain from {node_address}")
          return None
     except Exception as e:
          logger.error(f"Unexpected error fetching chain from {node_address}: {e}")
          return None

def announce_new_block(block_dict):
    active_peers = get_http_peers()
    if not active_peers:
         logger.info("No active peers found via Kademlia to announce block to.")
         
         # If no peers via Kademlia, try some heuristic approaches
         # Based on common network configurations
         try:
             # Special handling for Railway deployment
             if 'railway.app' in this_node_http_address:
                 base_url = this_node_http_address
                 
                 # Add scheme if missing
                 if not base_url.startswith(('http://', 'https://')):
                     base_url = f"https://{base_url}"
                     logger.info(f"Added https scheme to Railway URL: {base_url}")
                 
                 # Remove any semicolons that might be in the URL
                 base_url = base_url.replace(';', '')
                     
                 # Strip any existing node prefix
                 if '/node' in base_url:
                     base_url = base_url.split('/node')[0]
                 # Add paths for potential sibling nodes
                 for node_id in range(5):  # Try node0 through node4
                     node_url = f"{base_url}/node{node_id}"
                     # Don't add if it's our own address
                     if node_url != this_node_http_address:
                         logger.info(f"Adding Railway node by convention: {node_url}")
                         active_peers.add(node_url)
             else:
                 # Local network approach
                 hostname = socket.gethostname()
                 s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                 s.connect(('8.8.8.8', 80))
                 ip = s.getsockname()[0]
                 s.close()
                 
                 # Extract port from our HTTP address
                 our_port = int(this_node_http_address.split(':')[-1])
                 
                 # Try nodes on adjacent ports
                 for port_offset in range(1, 5):
                     # Try both higher and lower port numbers
                     for direction in [1, -1]:
                         if direction == -1 and our_port + direction * port_offset <= 0:
                             continue  # Skip invalid port
                         
                         test_port = our_port + direction * port_offset
                         test_addr = f"http://{ip}:{test_port}"
                         
                         # Don't add our own address
                         if test_addr == this_node_http_address:
                             continue
                             
                         logger.info(f"Adding heuristic peer for announcement: {test_addr}")
                         active_peers.add(test_addr)
         except Exception as e:
             logger.error(f"Error finding heuristic peers: {e}")
         
         if not active_peers:
             logger.warning("Still no peers found after heuristic search. Block announcement skipped.")
             return
         
    logger.info(f"Announcing new block #{block_dict['index']} to {len(active_peers)} peers: {active_peers}")
    block_json = json.dumps(block_dict, sort_keys=True)
    headers = {'Content-Type': "application/json"}

    announcements_sent = 0
    for node in active_peers:
         if node == this_node_http_address: continue
         thread = threading.Thread(target=send_announcement, args=(node, block_json, headers), daemon=True)
         thread.start()
         announcements_sent += 1
    
    logger.info(f"Sent {announcements_sent} block announcements to peers")
    
    # Give some time for announcements to be processed, then check consensus
    def delayed_consensus_check():
        try:
            time.sleep(5)  # Wait for announcements to be processed
            if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                logger.info("Running post-mining consensus check to ensure network synchronization")
                asyncio.run_coroutine_threadsafe(consensus(), kademlia_node.loop)
        except Exception as e:
            logger.error(f"Error in delayed consensus check: {e}")
    
    threading.Thread(target=delayed_consensus_check, daemon=True).start()

def send_announcement(node_address, data, headers):
     # Ensure URL has a scheme
     if not node_address.startswith(('http://', 'https://')):
         # For Railway, use https
         if 'railway.app' in node_address:
             node_address = f"https://{node_address}"
         else:
             node_address = f"http://{node_address}"
         logger.info(f"Added scheme to announcement URL: {node_address}")
     
     # Remove any semicolons that might be in the URL
     node_address = node_address.replace(';', '')
     
     # For Railway deployment with node paths, we need to make sure the URL includes /add_block properly
     if '/node' in node_address:
         # If URL already has a node path (e.g. railway.app/node1)
         url = f"{node_address}/add_block" if not node_address.endswith('/') else f"{node_address}add_block"
     else:
         # Standard URL format
         url = f"{node_address}/add_block"
     
     logger.info(f"Sending announcement to URL: {url}")
     
     # Try up to 3 times with increasing timeouts
     for attempt in range(3):
         try:
             timeout = 3 + attempt * 2  # 3, 5, 7 seconds
             logger.info(f"Announcing block to {node_address} (attempt {attempt+1}, timeout {timeout}s)")
             response = requests.post(url, data=data, headers=headers, timeout=timeout)
             
             if response.status_code == 201:
                 logger.info(f"Successfully announced block to {node_address}")
                 return
             elif response.status_code == 202:
                 # Accepted but processing, might need to retry
                 logger.info(f"Block announcement partially accepted by {node_address}: {response.text}")
                 # Wait a bit before the next retry
                 time.sleep(1)
             else:
                 logger.warning(f"Block announcement to {node_address} returned status {response.status_code}: {response.text}")
                 # Wait a bit before the next retry
                 time.sleep(1)
                 
         except requests.exceptions.Timeout:
             logger.warning(f"Timeout announcing block to {node_address} (attempt {attempt+1})")
             # Continue to next attempt
         except requests.exceptions.ConnectionError:
             logger.warning(f"Connection error announcing block to {node_address}")
             # Problem with the connection, break early
             break
         except Exception as e:
             logger.error(f"Unexpected error announcing block to {node_address}: {e}")
             # Break on unexpected errors
             break
     
     logger.warning(f"Failed to announce block to {node_address} after multiple attempts")

# Add a new function to verify chain consistency without modifying it
async def verify_chain_consistency():
    """
    Verify if this node's chain is consistent with the network majority
    without actually modifying the chain.
    """
    if not blockchain or len(blockchain.chain) == 0:
        return False
        
    # Get the hash of the last block in our chain
    our_last_hash = blockchain.last_block.hash
    our_chain_length = len(blockchain.chain)
    
    # Get the last hash from other peers to see if ours matches the majority
    active_peers = await get_active_peers_async()
    if not active_peers:
        logger.info("No peers available to verify chain consistency.")
        return True  # Can't verify, assume we're good
    
    logger.info(f"Verifying chain consistency with {len(active_peers)} peers: {active_peers}")
    
    # Collect the last hash from each peer
    peer_hashes = {}
    peer_lengths = {}
    
    tasks = []
    for node in active_peers:
        if node == this_node_http_address:
            continue
        tasks.append(get_peer_chain_info(node))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_results = 0
    errors = 0
    for i, result in enumerate(results):
        peer_node = active_peers[i] if i < len(active_peers) else "unknown"
        if isinstance(result, Exception):
            logger.warning(f"Error getting chain info from {peer_node}: {result}")
            errors += 1
            continue
        if result is None:
            logger.warning(f"No valid chain info from {peer_node}")
            continue
        
        peer_hash, peer_length = result
        logger.info(f"Peer {peer_node} has chain length {peer_length} with last hash {peer_hash[:8]}...")
        peer_hashes[peer_hash] = peer_hashes.get(peer_hash, 0) + 1
        peer_lengths[peer_length] = peer_lengths.get(peer_length, 0) + 1
        valid_results += 1
    
    if valid_results == 0:
        logger.warning(f"Could not get chain info from any peers ({errors} errors).")
        return True  # Can't verify, assume we're good
    
    # Check if our hash matches the majority hash
    if len(peer_hashes) == 0:
        logger.info("No peer hash data available for comparison.")
        return True  # No peer data, assume we're ok
        
    logger.info(f"Peer hash counts: {peer_hashes}")
    logger.info(f"Peer length counts: {peer_lengths}")
    
    majority_hash = max(peer_hashes.items(), key=lambda x: x[1])[0]
    majority_length = max(peer_lengths.items(), key=lambda x: x[1])[0]
    
    # We're consistent if our hash matches the majority or if our chain is longer
    is_consistent = (our_last_hash == majority_hash) or (our_chain_length >= majority_length)
    
    if not is_consistent:
        logger.warning(f"Our chain appears to be out of sync. Our length: {our_chain_length}, majority length: {majority_length}. Our hash: {our_last_hash[:8]}, majority hash: {majority_hash[:8]}")
    else:
        logger.info(f"Chain consistency verified: Our chain (length {our_chain_length}, hash {our_last_hash[:8]}...) matches or exceeds the network majority.")
    
    return is_consistent

async def get_peer_chain_info(peer_address):
    """Get the last block hash and chain length from a peer"""
    try:
        # Ensure URL has a scheme
        if not peer_address.startswith(('http://', 'https://')):
            # For Railway, use https
            if 'railway.app' in peer_address:
                peer_address = f"https://{peer_address}"
            else:
                peer_address = f"http://{peer_address}"
            logger.info(f"Added scheme to peer URL: {peer_address}")
        
        # Remove any semicolons that might be in the URL
        peer_address = peer_address.replace(';', '')
        
        # For Railway deployment with node paths, ensure URL is properly formed
        if '/node' in peer_address:
            chain_url = f"{peer_address}/chain" if not peer_address.endswith('/') else f"{peer_address}chain"
        else:
            chain_url = f"{peer_address}/chain"
            
        logger.info(f"Getting chain info from {chain_url}")
        
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.get(chain_url, timeout=3)
        )
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        chain = data.get('chain', [])
        
        if not chain:
            return None
            
        last_block = chain[-1]
        return last_block.get('hash'), len(chain)
    except Exception as e:
        logger.error(f"Error getting chain info from {peer_address}: {e}")
        return None

if __name__ == '__main__':
    load_chain() 
    setup_and_run_kademlia()
    
    # Start the mining worker thread
    miner_thread = threading.Thread(target=mine_worker, daemon=True)
    miner_thread.start()
    logger.info("Started background mining worker thread.")
    
    # Schedule periodic consensus checks
    def schedule_periodic_consensus():
        while True:
            try:
                time.sleep(60)  # Run consensus every 60 seconds
                if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                    asyncio.run_coroutine_threadsafe(consensus(), kademlia_node.loop)
                    logger.info("Periodic consensus check executed")
            except Exception as e:
                logger.error(f"Error in periodic consensus: {e}")
    
    consensus_thread = threading.Thread(target=schedule_periodic_consensus, daemon=True)
    consensus_thread.start()
    
    # Set up an immediate consensus check after startup
    # This is important to ensure quick synchronization
    def immediate_consensus():
        try:
            # Wait a short time for network to establish
            time.sleep(15)
            logger.info("Running immediate startup consensus check")
            if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                asyncio.run_coroutine_threadsafe(consensus(), kademlia_node.loop)
        except Exception as e:
            logger.error(f"Error in immediate consensus: {e}")
            
    threading.Thread(target=immediate_consensus, daemon=True).start()
    
    # Add additional periodic check for peer update in Railway environment
    if 'railway.app' in this_node_http_address:
        def railway_refresh_peers():
            while True:
                try:
                    time.sleep(120)  # Every 2 minutes
                    logger.info("Railway environment: Refreshing peer registration")
                    if kademlia_node and kademlia_node.running and kademlia_node.loop.is_running():
                        asyncio.run_coroutine_threadsafe(kademlia_node.register_self(), kademlia_node.loop)
                except Exception as e:
                    logger.error(f"Error in Railway peer refresh: {e}")
                    
        threading.Thread(target=railway_refresh_peers, daemon=True).start()
        logger.info("Started Railway-specific peer refresh thread")
    
    # Railway provides PORT environment variable
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 8000)))
    logger.info(f"Starting Flask server at port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
