#!/usr/bin/env python3
"""
Zoological Society - Initialization Script
A personal digital vault for managing video game collections.

This script initializes the project by:
1. Checking/installing requirements
2. Running the backend and frontend servers
3. Optionally setting up auto-start on boot
"""

import os
import sys
import json
import subprocess
import shutil
import socket

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, ".zoological_society.conf")
REQUIREMENTS_FILE = os.path.join(SCRIPT_DIR, "requirements.txt")
VENV_DIR = os.path.join(SCRIPT_DIR, "venv")
BACKEND_PORT = 9001
FRONTEND_PORT = 3021


def get_local_ip():
    """Detect the local IP address of the machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "localhost"


def check_requirements():
    """Check if virtual environment and dependencies are installed."""
    venv_python = os.path.join(VENV_DIR, "bin", "python")
    
    if not os.path.exists(VENV_DIR):
        print("Virtual environment not found. Creating...")
        return False
    
    if not os.path.exists(venv_python):
        print("Python in virtual environment not found.")
        return False
    
    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "show", "fastapi"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print("Dependencies not installed. Installing...")
            return False
    except Exception:
        return False
    
    return True


def install_requirements():
    """Install Python requirements."""
    print("Installing requirements...")
    
    if not os.path.exists(VENV_DIR):
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
    
    venv_pip = os.path.join(VENV_DIR, "bin", "pip")
    subprocess.run([venv_pip, "install", "-r", REQUIREMENTS_FILE], check=True)
    print("Requirements installed successfully.")


def load_config():
    """Load configuration from file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"auto_boot": False}


def save_config(config):
    """Save configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)


def ask_auto_boot():
    """Ask user if they want to initialize on boot."""
    config = load_config()
    
    print("\n" + "="*50)
    print("Zoological Society - Initialization")
    print("="*50)
    print("\nDo you want to initialize Zoological Society always on boot?")
    print("1) Yes")
    print("2) No")
    
    choice = input("Enter your choice (1/2): ").strip()
    
    if choice == "1":
        config["auto_boot"] = True
        print("\nAuto-boot enabled.")
    else:
        config["auto_boot"] = False
        print("\nAuto-boot disabled.")
    
    save_config(config)
    return config["auto_boot"]


def start_servers():
    """Start backend and frontend servers."""
    local_ip = get_local_ip()
    
    print("\n" + "="*60)
    print("  ZOOLOGICAL SOCIETY")
    print("="*60)
    print(f"\n  Backend:  http://localhost:{BACKEND_PORT}")
    print(f"  Frontend: http://localhost:{FRONTEND_PORT}")
    print(f"\n  ➤ To access from this computer, open:")
    print(f"    http://localhost:{FRONTEND_PORT}")
    print(f"\n  ➤ To access from another device on your network, open:")
    print(f"    http://{local_ip}:{FRONTEND_PORT}")
    print("\n" + "-"*60)
    print("  Press Ctrl+C to stop the servers.")
    print("-" * 60 + "\n")
    
    backend_process = subprocess.Popen(
        [os.path.join(VENV_DIR, "bin", "python"), "main.py"],
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    frontend_process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(FRONTEND_PORT)],
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    try:
        for line in iter(backend_process.stdout.readline, ''):
            print(f"[Backend] {line.rstrip()}")
    except KeyboardInterrupt:
        print("\n\nStopping servers...")
        backend_process.terminate()
        frontend_process.terminate()
        backend_process.wait()
        frontend_process.wait()
        print("Servers stopped.")
        sys.exit(0)


def main():
    """Main entry point."""
    os.chdir(SCRIPT_DIR)
    
    if not check_requirements():
        install_requirements()
    
    if not os.path.exists(CONFIG_FILE):
        ask_auto_boot()
    else:
        config = load_config()
        if "auto_boot" not in config:
            ask_auto_boot()
    
    start_servers()


if __name__ == "__main__":
    main()
