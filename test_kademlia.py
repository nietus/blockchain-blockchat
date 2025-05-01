#!/usr/bin/env python3
"""
Test script for Kademlia DHT implementation
This script allows you to test the Kademlia DHT functionality without starting a full blockchain node.
"""
import asyncio
import argparse
import signal
import sys
from kademlia_node import KademliaNode

async def test_dht(port, bootstrap_nodes, command, key=None, value=None):
    """Test different aspects of the Kademlia DHT"""
    print(f"Starting Kademlia node on port {port}")
    node = KademliaNode(port=port, bootstrap_nodes=bootstrap_nodes)
    
    # Create a signal handler to stop the node gracefully
    loop = asyncio.get_event_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                lambda: asyncio.create_task(shutdown(signame, node)))
    
    await node.start()
    
    if command == 'bootstrap':
        print("Node is running as a bootstrap node. Press Ctrl+C to exit.")
        # This node will just run and wait
        while True:
            await asyncio.sleep(1)
    
    elif command == 'get-nodes':
        nodes = await node.get_blockchain_nodes()
        print("\nKnown blockchain nodes:")
        if not nodes:
            print("  No nodes found")
        else:
            for i, n in enumerate(nodes, 1):
                print(f"  {i}. Host: {n.get('host', 'unknown')}, Port: {n.get('port', 'unknown')}")
        
        peers = await node.refresh_peers()
        print("\nPeer URLs:")
        if not peers:
            print("  No peers found")
        else:
            for i, p in enumerate(peers, 1):
                print(f"  {i}. {p}")
    
    elif command == 'set':
        if key and value:
            await node.server.set(key, value)
            print(f"Set {key} = {value}")
        else:
            print("Both key and value must be provided for 'set' command")
    
    elif command == 'get':
        if key:
            result = await node.server.get(key)
            print(f"Get {key} = {result}")
        else:
            print("Key must be provided for 'get' command")
    
    # Give a moment for any pending operations to complete
    await asyncio.sleep(1)
    
    # Close the node properly
    node.server.stop()
    print("Node stopped")

async def shutdown(signal, node):
    """Gracefully shutdown the node"""
    print(f"Received exit signal {signal}...")
    node.server.stop()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.get_event_loop().stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Kademlia DHT functionality")
    parser.add_argument('--port', type=int, default=5678, help='Port to listen on')
    parser.add_argument('--bootstrap', nargs='+', default=[], 
                        help='Bootstrap nodes in the format host:port')
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Bootstrap command
    bootstrap_parser = subparsers.add_parser('bootstrap', help='Run as a bootstrap node')
    
    # Get nodes command
    get_nodes_parser = subparsers.add_parser('get-nodes', help='Get known blockchain nodes')
    
    # Set key-value command
    set_parser = subparsers.add_parser('set', help='Set a key-value pair in the DHT')
    set_parser.add_argument('key', help='Key to set')
    set_parser.add_argument('value', help='Value to set')
    
    # Get key command
    get_parser = subparsers.add_parser('get', help='Get a value from the DHT')
    get_parser.add_argument('key', help='Key to get')
    
    args = parser.parse_args()
    
    # Default to bootstrap command if none provided
    if not args.command:
        args.command = 'bootstrap'
    
    # Parse bootstrap nodes
    bootstrap_nodes = []
    for node in args.bootstrap:
        try:
            host, port = node.split(':')
            bootstrap_nodes.append((host, int(port)))
        except ValueError:
            print(f"Invalid bootstrap node format: {node}. Should be host:port")
            sys.exit(1)
    
    # Run the appropriate command
    asyncio.run(test_dht(
        port=args.port,
        bootstrap_nodes=bootstrap_nodes,
        command=args.command,
        key=getattr(args, 'key', None),
        value=getattr(args, 'value', None)
    )) 