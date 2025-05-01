#!/usr/bin/env python3
"""
Test script to verify load balancing is working
This script makes multiple requests to test if different backend nodes are being used
"""
import requests
import time
import random
import collections
import argparse

def test_direct_backend_access(num_requests=20):
    """Make requests directly to each backend node to verify they're all working"""
    backends = [
        "http://backend1:8000/chain",
        "http://backend2:8001/chain",
        "http://backend3:8002/chain"
    ]
    
    results = {}
    
    print(f"Making {num_requests} requests to each backend...")
    
    for backend in backends:
        responses = []
        for i in range(num_requests):
            try:
                response = requests.get(backend, timeout=5)
                responses.append(response.status_code)
            except requests.exceptions.RequestException as e:
                responses.append(f"Error: {e}")
        
        success_rate = sum(1 for r in responses if r == 200) / len(responses) * 100
        results[backend] = {
            "responses": responses,
            "success_rate": success_rate
        }
    
    print("\n=== Direct Backend Access Results ===")
    for backend, data in results.items():
        print(f"{backend}: {data['success_rate']}% success rate")
        counter = collections.Counter(data['responses'])
        for status, count in counter.items():
            print(f"  - {status}: {count} times")
    
    return results

def test_frontend_node_selection(num_requests=50):
    """Make multiple requests to frontend APIs that should use random node selection"""
    # This needs to be run inside the frontend container
    from app.views import get_node_address
    
    selections = []
    print(f"Making {num_requests} random node selections...")
    
    for i in range(num_requests):
        node = get_node_address()
        selections.append(node)
    
    counter = collections.Counter(selections)
    
    print("\n=== Frontend Node Selection Results ===")
    total = sum(counter.values())
    for node, count in counter.items():
        percentage = count / total * 100
        print(f"{node}: {count} times ({percentage:.1f}%)")
    
    return counter

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test load balancing")
    parser.add_argument('--direct', action='store_true', 
                        help='Test direct access to backend nodes')
    parser.add_argument('--frontend', action='store_true',
                        help='Test frontend node selection (must run in frontend container)')
    parser.add_argument('--requests', type=int, default=20,
                        help='Number of requests to make')
    
    args = parser.parse_args()
    
    if args.direct or not (args.direct or args.frontend):
        test_direct_backend_access(args.requests)
    
    if args.frontend:
        test_frontend_node_selection(args.requests) 