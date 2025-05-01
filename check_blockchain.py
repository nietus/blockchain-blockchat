#!/usr/bin/env python3
"""
Diagnostic script to check the blockchain state on each node
"""
import json
import requests
import argparse
from pprint import pprint

def get_chain_from_node(node_url):
    """Get the blockchain from a specific node"""
    try:
        response = requests.get(f"{node_url}/chain", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"HTTP error {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def get_pending_tx_from_node(node_url):
    """Get the pending transactions from a specific node"""
    try:
        response = requests.get(f"{node_url}/pending_tx", timeout=5)
        if response.status_code == 200:
            return json.loads(response.text)
        else:
            return {"error": f"HTTP error {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def check_all_nodes(nodes):
    """Check the blockchain state on all nodes"""
    print(f"Checking blockchain state on {len(nodes)} nodes...")
    
    node_states = {}
    
    for node in nodes:
        print(f"\n=== Checking node: {node} ===")
        
        # Get the blockchain
        chain_data = get_chain_from_node(node)
        
        if "error" in chain_data:
            print(f"Error getting chain: {chain_data['error']}")
            continue
            
        chain_length = chain_data.get("length", 0)
        chain = chain_data.get("chain", [])
        peers = chain_data.get("peers", [])
        
        print(f"Chain length: {chain_length}")
        print(f"Peers: {', '.join(peers) if peers else 'None'}")
        
        # Get pending transactions
        pending_tx = get_pending_tx_from_node(node)
        
        if isinstance(pending_tx, dict) and "error" in pending_tx:
            print(f"Error getting pending transactions: {pending_tx['error']}")
            pending_tx = []
        
        print(f"Pending transactions: {len(pending_tx)}")
        
        if pending_tx:
            print("\nPending transactions:")
            for i, tx in enumerate(pending_tx, 1):
                print(f"  {i}. Author: {tx.get('author', 'Unknown')}")
                print(f"     Content: {tx.get('content', 'No content')[:50]}...")
                print(f"     Timestamp: {tx.get('timestamp', 'Unknown')}")
                print()
        
        # Collect all transactions from the blockchain
        all_tx = []
        for block in chain:
            transactions = block.get("transactions", [])
            all_tx.extend(transactions)
        
        print(f"Total transactions in blockchain: {len(all_tx)}")
        
        if all_tx:
            print("\nLast 5 transactions in blockchain:")
            for i, tx in enumerate(all_tx[-5:], 1):
                print(f"  {i}. Author: {tx.get('author', 'Unknown')}")
                print(f"     Content: {tx.get('content', 'No content')[:50]}...")
                print(f"     Timestamp: {tx.get('timestamp', 'Unknown')}")
                print(f"     Block: {tx.get('index', 'Unknown')}")
                print()
        
        # Store the node state for comparison
        node_states[node] = {
            "chain_length": chain_length,
            "tx_count": len(all_tx),
            "pending_tx": len(pending_tx)
        }
    
    # Compare states between nodes
    print("\n=== Comparison between nodes ===")
    for node, state in node_states.items():
        print(f"{node}: Chain length={state['chain_length']}, Transactions={state['tx_count']}, Pending={state['pending_tx']}")
    
    # Check for inconsistencies
    chain_lengths = [state["chain_length"] for state in node_states.values()]
    tx_counts = [state["tx_count"] for state in node_states.values()]
    
    if len(set(chain_lengths)) > 1:
        print("\nWARNING: Nodes have different chain lengths!")
    
    if len(set(tx_counts)) > 1:
        print("\nWARNING: Nodes have different transaction counts!")
    
    return node_states

def mine_block_on_node(node_url):
    """Mine a block on a specific node"""
    try:
        print(f"\nMining block on {node_url}...")
        response = requests.get(f"{node_url}/mine", timeout=10)
        if response.status_code == 200:
            print(f"Success: {response.text}")
            return True
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return False

def post_test_message(node_url, author="Test", content="Test message"):
    """Post a test message to a node"""
    try:
        print(f"\nPosting test message to {node_url}...")
        data = {
            "author": author,
            "content": content
        }
        response = requests.post(
            f"{node_url}/new_transaction",
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        if response.status_code == 201:
            print(f"Success: Message posted")
            return True
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check blockchain state")
    parser.add_argument('--nodes', nargs='+', default=[
        "http://backend1:8000",
        "http://backend2:8001",
        "http://backend3:8002"
    ], help='Nodes to check')
    parser.add_argument('--mine', action='store_true', help='Mine a block on each node')
    parser.add_argument('--post', action='store_true', help='Post a test message to each node')
    parser.add_argument('--author', default="Test", help='Author for test message')
    parser.add_argument('--content', default="Test message from diagnostic script", help='Content for test message')
    
    args = parser.parse_args()
    
    # Post test message if requested
    if args.post:
        for node in args.nodes:
            post_test_message(node, args.author, args.content)
    
    # Check blockchain state
    node_states = check_all_nodes(args.nodes)
    
    # Mine blocks if requested
    if args.mine:
        for node in args.nodes:
            mine_block_on_node(node)
        
        # Check blockchain state again after mining
        print("\n=== Checking blockchain state after mining ===")
        node_states = check_all_nodes(args.nodes) 