"""
Shell operations tool for the Devin Agent system.
Provides shell command and Python code execution.
"""

import subprocess
import sys
import os
import json
import traceback
from typing import Dict, Any, Optional, List
from pathlib import Path


class ShellTool:
    """Shell operations toolkit."""
    
    def __init__(self, workspace_root: str = ".", python_path: Optional[str] = None):
        """
        Initialize shell tool.
        
        Args:
            workspace_root: Root directory for file operations
            python_path: Path to Python interpreter
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.python_path = python_path or sys.executable
    
    def run_shell(self, command: str, timeout: int = 300,
                  cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None,
                  shell: bool = True) -> Dict[str, Any]:
        """
        Execute a shell command.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds
            cwd: Working directory (defaults to workspace root)
            env: Environment variables
            shell: Whether to use shell execution
            
        Returns:
            Dictionary with execution results
        """
        try:
            work_dir = Path(cwd).resolve() if cwd else self.workspace_root
            
            # Merge environment variables
            exec_env = os.environ.copy()
            if env:
                exec_env.update(env)
            
            # Execute command
            result = subprocess.run(
                command,
                shell=shell,
                cwd=str(work_dir),
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
                "working_dir": str(work_dir)
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "command": command,
                "timeout": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command
            }
    
    def run_python(self, code: str, timeout: int = 60,
                   globals_dict: Optional[Dict] = None,
                   locals_dict: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute Python code.
        
        Args:
            code: Python code to execute
            timeout: Timeout in seconds
            globals_dict: Optional globals dictionary
            locals_dict: Optional locals dictionary
            
        Returns:
            Dictionary with execution results
        """
        try:
            # Capture output
            stdout_buffer = []
            stderr_buffer = []
            
            def custom_write(msg):
                stdout_buffer.append(str(msg))
            
            def custom_error(msg):
                stderr_buffer.append(str(msg))
            
            # Prepare globals and locals
            if globals_dict is None:
                globals_dict = {
                    "__name__": "__main__",
                    "__builtins__": __builtins__
                }
            if locals_dict is None:
                locals_dict = globals_dict
            
            # Add workspace to path
            if str(self.workspace_root) not in sys.path:
                sys.path.insert(0, str(self.workspace_root))
            
            # Create a wrapper to capture print statements
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            
            try:
                sys.stdout = _StdoutCapture(stdout_buffer)
                sys.stderr = _StderrCapture(stderr_buffer)
                
                # Execute the code
                exec(code, globals_dict, locals_dict)
                
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr
            
            return {
                "success": True,
                "stdout": "".join(stdout_buffer),
                "stderr": "".join(stderr_buffer),
                "return_value": None  # Could capture return if needed
            }
        except TimeoutError:
            return {
                "success": False,
                "error": f"Python execution timed out after {timeout} seconds",
                "timeout": True
            }
        except Exception as e:
            # Capture the traceback
            tb_lines = traceback.format_exc().split('\n')
            
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "stdout": "".join(stdout_buffer),
                "stderr": "".join(stderr_buffer),
                "error_type": type(e).__name__
            }
    
    def check_command_available(self, command: str) -> bool:
        """Check if a command is available in the system."""
        try:
            result = subprocess.run(
                f"{command} --version",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_python_info(self) -> Dict[str, Any]:
        """Get information about the Python environment."""
        return {
            "python_path": sys.executable,
            "version": sys.version,
            "platform": sys.platform,
            "workspace": str(self.workspace_root)
        }


class _StdoutCapture:
    """Helper class to capture stdout."""
    
    def __init__(self, buffer: List[str]):
        self.buffer = buffer
    
    def write(self, text: str):
        self.buffer.append(text)
    
    def flush(self):
        pass


class _StderrCapture:
    """Helper class to capture stderr."""
    
    def __init__(self, buffer: List[str]):
        self.buffer = buffer
    
    def write(self, text: str):
        self.buffer.append(text)
    
    def flush(self):
        pass


# Convenience functions
def run_command(command: str, timeout: int = 300, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run a shell command (convenience function)."""
    tool = ShellTool(workspace_root=cwd or ".")
    return tool.run_shell(command, timeout=timeout, cwd=cwd)


def run_py(code: str, timeout: int = 60) -> Dict[str, Any]:
    """Run Python code (convenience function)."""
    tool = ShellTool()
    return tool.run_python(code, timeout=timeout)
