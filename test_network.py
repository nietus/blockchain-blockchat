#!/usr/bin/env python3
"""
Test script to verify node connectivity in the Docker network
"""
import sys
import json
import requests
import socket
import argparse

def test_node_connectivity(nodes):
    """Test connectivity to each node in the list"""
    print(f"Testing from host: {socket.gethostname()}")
    
    results = []
    for i, node in enumerate(nodes, 1):
        print(f"\nTesting node {i}: {node}")
        try:
            # Try to get the chain from the node
            response = requests.get(f"{node}/chain", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                chain_length = data.get('length', 0)
                peers = data.get('peers', [])
                
                print(f"✓ SUCCESS: Connected to {node}")
                print(f"  - Chain length: {chain_length}")
                print(f"  - Peers: {', '.join(peers) if peers else 'None'}")
                
                results.append({
                    "node": node,
                    "status": "success",
                    "chain_length": chain_length,
                    "peers": peers
                })
            else:
                print(f"✗ ERROR: Node returned status code {response.status_code}")
                results.append({
                    "node": node,
                    "status": "error",
                    "error": f"Status code: {response.status_code}"
                })
        except requests.exceptions.ConnectionError:
            print(f"✗ ERROR: Could not connect to {node}")
            results.append({
                "node": node,
                "status": "error",
                "error": "Connection refused"
            })
        except requests.exceptions.Timeout:
            print(f"✗ ERROR: Connection to {node} timed out")
            results.append({
                "node": node,
                "status": "error",
                "error": "Connection timeout"
            })
        except Exception as e:
            print(f"✗ ERROR: Unexpected error: {e}")
            results.append({
                "node": node,
                "status": "error",
                "error": str(e)
            })
    
    # Summary
    successful = sum(1 for r in results if r["status"] == "success")
    print(f"\nSummary: {successful}/{len(nodes)} nodes reachable")
    
    return results

def post_test_transaction(node, author="TestScript", content="Test transaction from test_network.py"):
    """Post a test transaction to a node"""
    print(f"\nPosting test transaction to {node}")
    
    try:
        post_object = {
            'author': author,
            'content': content,
        }
        
        response = requests.post(
            f"{node}/new_transaction",
            json=post_object,
            headers={'Content-type': 'application/json'},
            timeout=5
        )
        
        if response.status_code == 201:
            print(f"✓ SUCCESS: Transaction posted to {node}")
            return True
        else:
            print(f"✗ ERROR: Node returned status code {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False

def mine_block(node):
    """Mine a block on a specific node"""
    print(f"\nMining block on {node}")
    
    try:
        response = requests.get(f"{node}/mine", timeout=10)
        
        if response.status_code == 200:
            print(f"✓ SUCCESS: Block mined on {node}")
            print(f"  - Response: {response.text}")
            return True
        else:
            print(f"✗ ERROR: Node returned status code {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test blockchain node connectivity")
    parser.add_argument('--nodes', nargs='+', default=[], 
                        help='Nodes to test (e.g., http://backend1:8000)')
    parser.add_argument('--post', action='store_true',
                        help='Post a test transaction to the first available node')
    parser.add_argument('--mine', action='store_true',
                        help='Mine a block on the first available node')
    
    args = parser.parse_args()
    
    # Default nodes in the Docker environment
    default_nodes = [
        "http://backend1:8000",
        "http://backend2:8001",
        "http://backend3:8002"
    ]
    
    # Use provided nodes or default
    nodes = args.nodes if args.nodes else default_nodes
    
    # Test connectivity
    results = test_node_connectivity(nodes)
    
    # Get available nodes (successful connections)
    available_nodes = [r["node"] for r in results if r["status"] == "success"]
    
    # Post a test transaction if requested
    if args.post and available_nodes:
        post_test_transaction(available_nodes[0])
    
    # Mine a block if requested
    if args.mine and available_nodes:
        mine_block(available_nodes[0]) 