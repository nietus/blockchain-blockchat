#!/usr/bin/env python3
"""
Diagnostic script to help identify network issues in the Docker environment
"""
import socket
import subprocess
import os
import sys
import json
import argparse

def get_container_info():
    """Get information about the current container"""
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    
    env_vars = {k: v for k, v in os.environ.items() if k.startswith('FLASK') or k.startswith('KADEMLIA')}
    
    print(f"Container Hostname: {hostname}")
    print(f"Container IP Address: {ip_address}")
    print("\nRelevant Environment Variables:")
    for key, value in env_vars.items():
        print(f"  {key}={value}")
    
    return hostname, ip_address, env_vars

def check_dns_resolution(targets):
    """Check if DNS resolution works for target hosts"""
    print("\nDNS Resolution Test:")
    
    for target in targets:
        try:
            print(f"  Resolving {target}... ", end='')
            ip_address = socket.gethostbyname(target)
            print(f"Success! IP: {ip_address}")
        except socket.gaierror as e:
            print(f"Failed! Error: {e}")

def ping_hosts(targets):
    """Ping target hosts to check connectivity"""
    print("\nPing Test:")
    
    for target in targets:
        print(f"  Pinging {target}... ", end='')
        try:
            # Using subprocess to call ping command
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                print("Success!")
            else:
                print(f"Failed! Host unreachable")
                print(f"    Command output: {result.stdout.strip()}")
        except subprocess.TimeoutExpired:
            print("Failed! Ping timed out")
        except Exception as e:
            print(f"Failed! Error: {e}")

def check_port_open(targets, ports):
    """Check if specific ports are open on target hosts"""
    print("\nPort Connection Test:")
    
    for target in targets:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            
            try:
                print(f"  Connecting to {target}:{port}... ", end='')
                result = sock.connect_ex((target, port))
                
                if result == 0:
                    print("Success! Port is open")
                else:
                    print(f"Failed! Port is closed (Error code: {result})")
            except socket.gaierror:
                print(f"Failed! Cannot resolve hostname")
            except socket.timeout:
                print(f"Failed! Connection timed out")
            except Exception as e:
                print(f"Failed! Error: {e}")
            finally:
                sock.close()

def check_udp_ports(targets, ports):
    """Check UDP port connectivity to target hosts"""
    print("\nUDP Port Test:")
    
    for target in targets:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            
            try:
                print(f"  Sending UDP packet to {target}:{port}... ", end='')
                sock.sendto(b"Hello", (target, port))
                # Note: UDP is connectionless, so we can't really verify if the port is open
                # But at least we can check if we can send packets without errors
                print("Packet sent without errors (but no reply expected)")
            except socket.gaierror:
                print(f"Failed! Cannot resolve hostname")
            except socket.timeout:
                print(f"Failed! Connection timed out")
            except Exception as e:
                print(f"Failed! Error: {e}")
            finally:
                sock.close()

def run_diagnostics(targets=None, tcp_ports=None, udp_ports=None):
    """Run all diagnostics"""
    print("=== Docker Network Diagnostics ===")
    
    # Default targets and ports if not specified
    if targets is None:
        targets = ["backend1", "backend2", "backend3"]
    
    if tcp_ports is None:
        tcp_ports = [8000, 8001, 8002]
    
    if udp_ports is None:
        udp_ports = [5678, 5679, 5680]
    
    # Get container info
    hostname, ip_address, env_vars = get_container_info()
    
    # Remove current container from targets to avoid self-ping
    if hostname in targets:
        targets.remove(hostname)
    
    # Check DNS resolution
    check_dns_resolution(targets)
    
    # Ping hosts
    ping_hosts(targets)
    
    # Check TCP port connectivity
    check_port_open(targets, tcp_ports)
    
    # Check UDP port connectivity
    check_udp_ports(targets, udp_ports)
    
    print("\n=== Diagnostics Complete ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose Docker network issues")
    parser.add_argument('--targets', nargs='+', help='Target hostnames to check')
    parser.add_argument('--tcp-ports', type=int, nargs='+', help='TCP ports to check')
    parser.add_argument('--udp-ports', type=int, nargs='+', help='UDP ports to check')
    
    args = parser.parse_args()
    
    run_diagnostics(
        targets=args.targets,
        tcp_ports=args.tcp_ports,
        udp_ports=args.udp_ports
    ) 