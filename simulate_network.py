import asyncio
import threading
import os
import sys
import time
import random
import json
from kademlia_node import KademliaNode
from node_server import Block, Blockchain, save_chain, load_chain

class SimulatedNode:
    def __init__(self, node_id, kademlia_port, http_port, bootstrap_nodes=None):
        self.node_id = node_id
        self.kademlia_port = kademlia_port
        self.http_port = http_port
        self.http_address = f"http://127.0.0.1:{http_port}"
        self.blockchain = Blockchain()
        self.unconfirmed_transactions = []
        
        # Initialize Kademlia node
        self.kademlia_node = KademliaNode(
            port=kademlia_port,
            bootstrap_nodes=bootstrap_nodes or [],
            http_address=self.http_address
        )
        
    async def start(self):
        """Start the simulated node"""
        print(f"Starting simulated node {self.node_id} (HTTP: {self.http_port}, Kademlia: {self.kademlia_port})")
        await self.kademlia_node.start()
        
    async def add_transaction(self, transaction):
        """Add a transaction to the node"""
        if not all(k in transaction for k in ('author', 'content', 'timestamp')):
            print(f"Node {self.node_id}: Transaction missing required fields")
            return False
        
        self.blockchain.add_new_transaction(transaction)
        # In a real network, we would broadcast this transaction
        return True
        
    async def mine(self):
        """Mine a new block"""
        result = self.blockchain.mine()
        if result:
            print(f"Node {self.node_id}: Mined block #{result}")
            # In a real network, we would announce this block
            return result
        else:
            print(f"Node {self.node_id}: No transactions to mine")
            return False
    
    async def get_peers(self):
        """Get peers from Kademlia"""
        if self.kademlia_node and self.kademlia_node.running:
            peers = await self.kademlia_node.get_active_blockchain_peers()
            return peers
        return []
        
    def get_chain(self):
        """Get the current blockchain"""
        chain_data = [block.to_dict() for block in self.blockchain.chain]
        return {"length": len(chain_data), "chain": chain_data}
        
    async def sync_with_network(self):
        """Sync blockchain with other nodes"""
        peers = await self.get_peers()
        if not peers:
            print(f"Node {self.node_id}: No peers to sync with")
            return False
            
        print(f"Node {self.node_id}: Syncing with peers: {peers}")
        # In a real network, we would implement the consensus algorithm here
        return True

class SimulatedNetwork:
    def __init__(self, num_nodes=3):
        self.num_nodes = num_nodes
        self.nodes = []
        self.base_kademlia_port = 5678
        self.base_http_port = 8000
        
    async def setup(self):
        """Set up the simulated network"""
        # Create the first node (bootstrap node)
        bootstrap_node = SimulatedNode(
            node_id=0,
            kademlia_port=self.base_kademlia_port,
            http_port=self.base_http_port
        )
        await bootstrap_node.start()
        self.nodes.append(bootstrap_node)
        
        # Wait for the bootstrap node to start
        await asyncio.sleep(2)
        
        # Create additional nodes
        bootstrap_nodes = [(f"127.0.0.1", self.base_kademlia_port)]
        for i in range(1, self.num_nodes):
            node = SimulatedNode(
                node_id=i,
                kademlia_port=self.base_kademlia_port + i,
                http_port=self.base_http_port + i,
                bootstrap_nodes=bootstrap_nodes
            )
            await node.start()
            self.nodes.append(node)
            await asyncio.sleep(1)  # Give the node time to connect
            
        print(f"Simulated network with {self.num_nodes} nodes is running")
        
    async def simulate_activity(self, num_transactions=5):
        """Simulate network activity"""
        # Create random transactions
        for _ in range(num_transactions):
            # Pick a random node to create the transaction
            node = random.choice(self.nodes)
            
            # Create a transaction
            transaction = {
                "author": f"user_{random.randint(1, 100)}",
                "content": f"Message {random.randint(1000, 9999)}",
                "timestamp": int(time.time() * 1000)
            }
            
            # Add transaction to the node
            await node.add_transaction(transaction)
            print(f"Added transaction from {transaction['author']} to node {node.node_id}")
            
            # Small delay between transactions
            await asyncio.sleep(0.5)
            
        # Mine blocks
        for node in self.nodes:
            result = await node.mine()
            if result:
                # Allow time for block propagation
                await asyncio.sleep(1)
                
        # Sync chains
        for node in self.nodes:
            await node.sync_with_network()
            
        # Print chain information
        for node in self.nodes:
            chain_info = node.get_chain()
            print(f"Node {node.node_id} chain length: {chain_info['length']}")
            
async def main():
    # Create a simulated network with 3 nodes
    network = SimulatedNetwork(num_nodes=3)
    await network.setup()
    
    # Simulate some activity
    await network.simulate_activity(num_transactions=5)
    
    # Keep the network running
    print("Network is running. Press Ctrl+C to exit.")
    try:
        while True:
            await asyncio.sleep(10)
            await network.simulate_activity(num_transactions=2)
    except KeyboardInterrupt:
        print("Shutting down network simulation...")

if __name__ == "__main__":
    asyncio.run(main()) 