"""System operations - command injection vulnerabilities."""
import os
import subprocess

def ping_host(hostname):
    """COMMAND INJECTION (1) - os.system with f-string."""
    result = os.system(f"ping -c 1 {hostname}")
    return result

def run_backup(target_path):
    """COMMAND INJECTION (2) - shell=True with f-string."""
    output = subprocess.check_output(f"tar -czf /tmp/backup.tar.gz {target_path}", shell=True)
    return output

def list_directory(dir_path):
    """Safe - NOT vulnerable."""
    return os.listdir(dir_path)

def run_git_status(repo_path):
    """Safe - NOT vulnerable."""
    return subprocess.run(["git", "status", repo_path], capture_output=True, text=True)
