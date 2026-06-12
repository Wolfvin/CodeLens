"""Clean system ops - safe subprocess usage."""
import os
import subprocess
from typing import List

def ping_host(hostname: str) -> int:
    result = subprocess.run(["ping", "-c", "1", hostname], capture_output=True, text=True)
    return result.returncode

def run_backup(target_path: str) -> bytes:
    return subprocess.check_output(["tar", "-czf", "/tmp/backup.tar.gz", target_path])

def list_directory(dir_path: str) -> List[str]:
    return os.listdir(dir_path)

def run_git_status(repo_path: str) -> str:
    result = subprocess.run(["git", "status", repo_path], capture_output=True, text=True)
    return result.stdout
