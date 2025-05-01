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
            announce_new_block(new_block.to_dict())
            return new_block.index
        else:
            logger.error(f"Failed to add mined block {new_block.index}")
            return False


app = Flask(__name__)
CORS(app)

# Handle URL prefixes for Railway deployment
node_prefix = os.environ.get('NODE_PREFIX', '')
if node_prefix:
    # In Railway deployment, create a blueprint with prefix
    bp = Blueprint('node', __name__, url_prefix=node_prefix)
else:
    # In local development, use the app directly
    bp = app

blockchain = None
kademlia_node = None
kademlia_thread = None

# Handle Railway deployment URL
railway_url = os.environ.get('RAILWAY_STATIC_URL', '')
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

def setup_and_run_kademlia():
    global kademlia_node, kademlia_thread
    if kademlia_node and kademlia_node.running:
        logger.info("Kademlia already initialized and running.")
        return
        
    kademlia_port = int(os.environ.get('KADEMLIA_PORT', 5678))
    kademlia_bootstrap_env = os.environ.get('KADEMLIA_BOOTSTRAP', '')
    bootstrap_nodes = []
    if kademlia_bootstrap_env:
        for node_str in kademlia_bootstrap_env.split(','):
            if node_str.strip():
                try:
                    host, port_str = node_str.strip().split(':')
                    bootstrap_nodes.append((host, int(port_str)))
                except ValueError:
                    logger.warning(f"Invalid bootstrap node format: {node_str}. Ignoring.")

    logger.info(f"Initializing Kademlia DHT on port {kademlia_port} with bootstrap nodes: {bootstrap_nodes}")
    try:
        kademlia_node = KademliaNode(port=kademlia_port, 
                                   bootstrap_nodes=bootstrap_nodes,
                                   http_address=this_node_http_address)
        kademlia_thread = kademlia_node.run_in_thread()
        if not kademlia_node.running:
             logger.error("Kademlia thread started but node failed to run (maybe port conflict?)")
        else:
             logger.info("Kademlia node started successfully in background thread.")
             
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

def graceful_shutdown():
     logger.info("Initiating graceful shutdown...")
     save_chain() 
     if kademlia_node:
          kademlia_node.stop()
     logger.info("Shutdown complete.")

atexit.register(graceful_shutdown)

@bp.route('/new_transaction', methods=['POST'])
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
def get_chain():
    if not blockchain:
         return "Blockchain not initialized", 500
    chain_data = [block.to_dict() for block in blockchain.chain]
    active_peers = get_http_peers()
    return json.dumps({"length": len(chain_data),
                       "chain": chain_data,
                       "peers": list(active_peers) })

@bp.route('/mine', methods=['GET'])
def mine_unconfirmed_transactions():
    if not blockchain:
         return "Blockchain not initialized", 500
    result = blockchain.mine()
    if result is False:
        return "No transactions to mine or failed to add block", 200
    else:
        return f"Block #{result} is mined.", 200

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

        if any(b.index == block_data['index'] and b.hash == block_data['hash'] for b in blockchain.chain):
             return "Block already exists", 200
             
        last_block = blockchain.last_block
        if block_data['previous_hash'] == last_block.hash and block_data['index'] == last_block.index + 1:
            block = Block(block_data['index'], block_data['transactions'], block_data['timestamp'],
                          block_data['previous_hash'], block_data['nonce'])
            if blockchain.add_block(block, block_data['hash']):
                 logger.info(f"Received block {block.index} added sequentially.")
                 return "Block added to the chain", 201
            else:
                 logger.warning(f"Received block {block.index} failed validation.")
                 return "Block rejected by node (validation failed)", 400
        elif block_data['index'] > last_block.index:
             logger.warning(f"Received block {block_data['index']} which is ahead of local chain (length {len(blockchain.chain)}). Triggering consensus.")
             asyncio.run_coroutine_threadsafe(consensus(), kademlia_node.loop if kademlia_node else asyncio.get_event_loop())
             return "Received block from longer chain, running consensus", 202
        else:
             return "Block is older than current chain head", 200

    except Exception as e:
        logger.error(f"Error processing received block: {e}", exc_info=True)
        return "Internal server error processing block", 500

@bp.route('/pending_tx')
def get_pending_tx():
     if not blockchain:
          return "Blockchain not initialized", 500
     return json.dumps(blockchain.unconfirmed_transactions)

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
    logger.info(f"Found {len(active_peers)} active peers via Kademlia for consensus.")

    tasks = []
    for node in active_peers:
         if node == this_node_http_address: continue
         tasks.append(fetch_chain_from_peer(node))
         
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_peer_chains = []
    for i, result in enumerate(results):
         peer_node = list(active_peers)[i]
         if isinstance(result, Exception):
              logger.warning(f"Consensus error fetching chain from {peer_node}: {result}")
         elif result:
              length, chain = result
              if length > max_len and blockchain.check_chain_validity(chain):
                   logger.info(f"Longer valid chain found at {peer_node} (length {length})")
                   max_len = length
                   longest_chain = chain
         pass

    if longest_chain:
        blockchain.chain = longest_chain 
        logger.info(f"Consensus successful: Replaced local chain (length {current_len}) with new chain (length {max_len}).")
        save_chain()
        return True
    else:
        logger.info("Consensus check complete: Local chain remains authoritative.")
        return False

async def fetch_chain_from_peer(node_address):
     logger.debug(f"Fetching chain from {node_address}...")
     try:
          loop = asyncio.get_running_loop()
          response = await loop.run_in_executor(None, lambda: requests.get(f'{node_address}/chain', timeout=5))
          response.raise_for_status() 
          data = response.json()
          length = data['length']
          chain_dump = data['chain']
          
          chain_objects = []
          for block_data in chain_dump:
                block = Block(block_data['index'], block_data['transactions'], block_data['timestamp'],
                              block_data['previous_hash'], block_data['nonce'])
                block.hash = block_data['hash']
                chain_objects.append(block)
                
          if Blockchain.check_chain_validity(chain_objects):
               return length, chain_objects
          else:
               logger.warning(f"Received invalid chain from {node_address}")
               return None
     except requests.exceptions.Timeout:
          logger.warning(f"Timeout fetching chain from {node_address}")
          return None
     except requests.exceptions.RequestException as e:
          logger.warning(f"Request error fetching chain from {node_address}: {e}")
          return None
     except json.JSONDecodeError as e:
          logger.error(f"JSON decode error from {node_address}: {e}")
          return None
     except Exception as e:
          logger.error(f"Unexpected error fetching chain from {node_address}: {e}", exc_info=True)
          return None

def announce_new_block(block_dict):
    active_peers = get_http_peers()
    if not active_peers:
         logger.info("No active peers found via Kademlia to announce block to.")
         return
         
    logger.info(f"Announcing new block #{block_dict['index']} to {len(active_peers)} peers: {active_peers}")
    block_json = json.dumps(block_dict, sort_keys=True)
    headers = {'Content-Type': "application/json"}

    for node in active_peers:
         if node == this_node_http_address: continue
         thread = threading.Thread(target=send_announcement, args=(node, block_json, headers), daemon=True)
         thread.start()

def send_announcement(node_address, data, headers):
     url = f"{node_address}/add_block"
     try:
          response = requests.post(url, data=data, headers=headers, timeout=3)
          logger.debug(f"Announced block to {node_address}: Status {response.status_code}")
     except requests.exceptions.Timeout:
          logger.warning(f"Timeout announcing block to {node_address}")
     except requests.exceptions.RequestException as e:
          logger.warning(f"Failed to announce block to {node_address}: {e}")
     except Exception as e:
          logger.error(f"Unexpected error announcing block to {node_address}: {e}")

# Register blueprint if using prefixes
if node_prefix:
    app.register_blueprint(bp)

if __name__ == '__main__':
    load_chain() 
    setup_and_run_kademlia()
    
    # Railway provides PORT environment variable
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 8000)))
    logger.info(f"Starting Flask server at port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
