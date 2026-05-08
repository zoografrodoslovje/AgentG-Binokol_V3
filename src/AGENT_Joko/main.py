"""
Main CLI entry point for the Devin Agent system.
A local autonomous AI developer (Devin-level) using Ollama models.
"""

import sys
import os
import json
import time
import argparse
import shutil
from pathlib import Path
from typing import Optional

# Try to import colorama for Windows compatibility
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Stub out color codes if not available
    class Fore:
        BLACK = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = RESET = ''
    class Back:
        BLACK = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = RESET = ''
    class Style:
        BRIGHT = DIM = NORMAL = RESET_ALL = ''

from .config import Config, get_config, set_config
from .orchestrator import Orchestrator, ExecutionResult
from .task_queue import TaskPriority


# Color helpers
def colored(text: str, color: str) -> str:
    """Apply color to text."""
    if not COLORAMA_AVAILABLE:
        return text
    return f"{color}{text}{Fore.RESET}"


def success(text: str) -> str:
    """Green success text."""
    return colored(text, Fore.GREEN)


def error(text: str) -> str:
    """Red error text."""
    return colored(text, Fore.RED)


def warning(text: str) -> str:
    """Yellow warning text."""
    return colored(text, Fore.YELLOW)


def info(text: str) -> str:
    """Cyan info text."""
    return colored(text, Fore.CYAN)


def header(text: str) -> str:
    """Bright header text."""
    if not COLORAMA_AVAILABLE:
        return text
    return f"{Style.BRIGHT}{Fore.WHITE}{text}{Style.RESET_ALL}"


def subheader(text: str) -> str:
    """Blue subheader text."""
    return colored(text, Fore.BLUE)


def dim(text: str) -> str:
    """Dimmed text."""
    if not COLORAMA_AVAILABLE:
        return text
    return f"{Style.DIM}{text}{Style.RESET_ALL}"


class DevinCLI:
    """
    Command-line interface for the Devin Agent system.
    """
    
    BANNER = r"""
     _  _     _     _                    _                 _ 
    | || |___| |__ | |__  __ _ _ __ __| |   ___ __ _ _ __| |
    | __ / _ \ '_ \| '_ \/ _` | '__/ _` |  / -_) _` | '_ \ |
   |_||_\___/|_.__/|_.__/\__,_|_|  \__,_| \___\__,_| .__/_|
                                                   |_|     
    """
    
    def __init__(self, workspace: str = ".", verbose: bool = False):
        """
        Initialize the CLI.
        
        Args:
            workspace: Workspace directory
            verbose: Enable verbose output
        """
        self.workspace = Path(workspace).resolve()
        self.verbose = verbose
        self.orchestrator: Optional[Orchestrator] = None
        
        # Create workspace if needed
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        # Load or create config
        self._init_config()
    
    def _init_config(self):
        """Initialize configuration."""
        config = Config()
        config.workspace_root = str(self.workspace)
        config.verbose = self.verbose
        
        # Try to load existing config
        config_file = self.workspace / ".devin_agent" / "config.json"
        if config_file.exists():
            try:
                config = Config.load(str(config_file))
                config.workspace_root = str(self.workspace)
            except Exception:
                pass
        else:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config.save(str(config_file))

        # Always keep memory storage inside the workspace to avoid permission issues
        # and to keep runs portable under Pinokio.
        config.memory.storage_path = str((self.workspace / ".devin_agent" / "memory").resolve())
        
        set_config(config)
        self.config = config
    
    def _init_orchestrator(self):
        """Initialize the orchestrator."""
        if self.orchestrator is None:
            self.orchestrator = Orchestrator(self.config)
        return self.orchestrator
    
    def print_banner(self):
        """Print the welcome banner."""
        print(header(self.BANNER))
        print(dim("=" * 60))
        print(info("  Hybrid Local Autonomous AI Developer"))
        print(info("  Powered by Ollama + OpenRouter"))
        print(dim("=" * 60))
        print()
    
    def print_status(self):
        """Print current status."""
        orch = self._init_orchestrator()
        status = orch.get_status()
        
        print()
        print(header("Status"))
        print(dim("-" * 40))
        print(f"  Session: {status['session_id']}")
        print(f"  Running: {status['running']}")
        print(f"  Queue: {status['queue_stats']['pending']} pending, {status['queue_stats']['completed']} completed")
        
        if status.get('git_status'):
            git = status['git_status']
            print(f"  Git: {git.get('current_branch', 'N/A')} ({'clean' if git.get('clean') else 'dirty'})")
        
        print()
    
    def cmd_execute(self, goal: str, workflow: Optional[str] = None):
        """
        Execute a goal.
        
        Args:
            goal: The goal/requirement
            workflow: Optional workflow type
        """
        orch = self._init_orchestrator()
        
        print()
        print(subheader(f"Executing: {goal[:60]}..."))
        print(dim("-" * 40))
        
        result = orch.execute_goal(goal, workflow)
        
        if result.success:
            print()
            print(success(f"✓ {result.message}"))
            
            if result.data:
                print()
                print(info("Results:"))
                if isinstance(result.data, str):
                    print(result.data)
                else:
                    print(json.dumps(result.data, indent=2))
        else:
            print()
            print(error(f"✗ {result.message}"))
            if result.error:
                print(error(f"  Error: {result.error}"))
        
        return result
    
    def cmd_shell(self, command: str):
        """Execute a shell command."""
        orch = self._init_orchestrator()
        
        print()
        print(subheader(f"$ {command}"))
        print(dim("-" * 40))
        
        result = orch.shell(command)
        
        if result.get("success"):
            if result.get("stdout"):
                print(result["stdout"])
        else:
            print(error(f"Error: {result.get('error', 'Unknown')}"))
            if result.get("stderr"):
                print(error(result["stderr"]))
        
        return result
    
    def cmd_python(self, code: str):
        """Execute Python code."""
        orch = self._init_orchestrator()
        
        print()
        print(subheader(">>> Python Execute"))
        print(dim("-" * 40))
        
        result = orch.python(code)
        
        if result.get("success"):
            if result.get("stdout"):
                print(result["stdout"])
            if result.get("stderr"):
                print(warning(result["stderr"]))
        else:
            print(error(f"Error: {result.get('error', 'Unknown')}"))
            if result.get("traceback"):
                print(error(result["traceback"]))
        
        return result
    
    def cmd_read(self, path: str, limit: int = 100):
        """Read a file."""
        orch = self._init_orchestrator()
        
        print()
        print(subheader(f"Reading: {path}"))
        print(dim("-" * 40))
        
        result = orch.read_file(path, limit=limit)
        
        if result.get("success"):
            print(result["content"])
            if result.get("truncated"):
                print(dim(f"\n... (truncated, {result['total_lines']} total lines)"))
        else:
            print(error(f"Error: {result.get('error', 'Unknown')}"))
        
        return result
    
    def cmd_write(self, path: str, content: str):
        """Write a file."""
        orch = self._init_orchestrator()
        
        print()
        print(subheader(f"Writing: {path}"))
        
        result = orch.write_file(path, content)
        
        if result.get("success"):
            print(success(f"✓ File written ({result.get('bytes', 0)} bytes)"))
        else:
            print(error(f"Error: {result.get('error', 'Unknown')}"))
        
        return result
    
    def cmd_git(self, *args):
        """Execute a git command."""
        orch = self._init_orchestrator()
        
        cmd_str = " ".join(args)
        print()
        print(subheader(f"$ git {cmd_str}"))
        print(dim("-" * 40))
        
        result = orch.git(*args)
        
        if result.get("success"):
            if result.get("stdout"):
                print(result["stdout"])
        else:
            print(error(f"Error: {result.get('error', 'Unknown')}"))
            if result.get("stderr"):
                print(error(result["stderr"]))
        
        return result
    
    def cmd_queue_list(self):
        """List tasks in the queue."""
        orch = self._init_orchestrator()
        
        print()
        print(header("Task Queue"))
        print(dim("-" * 40))
        
        stats = orch.task_queue.get_stats()
        print(f"  Total: {stats['total']}")
        print(f"  Pending: {stats['pending']}")
        print(f"  In Progress: {stats['in_progress']}")
        print(f"  Completed: {stats['completed']}")
        print(f"  Failed: {stats['failed']}")
        
        print()
        print(info("Pending Tasks:"))
        for task in orch.task_queue.get_pending():
            priority_indicator = {
                TaskPriority.LOW: dim("[L]"),
                TaskPriority.NORMAL: "[N]",
                TaskPriority.HIGH: warning("[H]"),
                TaskPriority.CRITICAL: error("[!]")
            }.get(task.priority, "[N]")
            print(f"  {priority_indicator} {task.id}: {task.description[:50]}")
        
        return stats
    
    def cmd_queue_add(self, description: str, priority: str = "normal"):
        """Add a task to the queue."""
        orch = self._init_orchestrator()
        
        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL
        }
        
        priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)
        
        task = orch.add_task(description, priority)
        
        print()
        print(success(f"✓ Task added: {task.id}"))
        print(dim(f"  Description: {task.description}"))
        print(dim(f"  Priority: {priority.name}"))
        
        return task
    
    def cmd_queue_run(self, max_iterations: int = 100):
        """Run tasks from the queue."""
        orch = self._init_orchestrator()
        
        print()
        print(subheader("Running task queue..."))
        print(dim("-" * 40))
        
        results = orch.run_queue(max_iterations)
        
        print()
        print(success(f"✓ Queue run complete"))
        print(f"  Completed: {results['completed']}")
        print(f"  Failed: {results['failed']}")
        print(f"  Iterations: {results['iterations']}")
        
        return results
    
    def cmd_memory_stats(self):
        """Show memory statistics."""
        orch = self._init_orchestrator()
        
        print()
        print(header("Memory Statistics"))
        print(dim("-" * 40))
        
        stats = orch.memory_store.get_stats()
        
        print(f"  Total entries: {stats['total_entries']}")
        print(f"  Storage path: {stats['storage_path']}")
        print()
        print(info("By type:"))
        for entry_type, count in stats.get("by_type", {}).items():
            print(f"  - {entry_type}: {count}")
        
        print()
        print(info("Tags:"))
        for tag in stats.get("tags", [])[:10]:
            print(f"  - {tag}")
        
        return stats
    
    def cmd_agent(self, agent_name: str, task: str):
        """Run a specific agent directly."""
        orch = self._init_orchestrator()
        
        agent = orch.get_agent(agent_name)
        if not agent:
            print(error(f"Unknown agent: {agent_name}"))
            return None
        
        print()
        print(subheader(f"Running {agent_name} agent..."))
        print(dim("-" * 40))
        
        result = agent.process(task)
        
        if result.success:
            print(success(f"✓ {agent_name} completed"))
            print()
            print(result.content)
        else:
            print(error(f"✗ {agent_name} failed: {result.error}"))
        
        return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AGENT_Joko - Hybrid local/OpenRouter autonomous AI developer",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--workspace", "-w",
        default=".",
        help="Workspace directory (default: current directory)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Execute command
    exec_parser = subparsers.add_parser("execute", aliases=["exec", "e"],
                                        help="Execute a goal")
    exec_parser.add_argument("goal", help="Goal/requirement to accomplish")
    exec_parser.add_argument("--workflow", "-w", choices=["full", "debate_only", "code_only"],
                           help="Workflow type")
    
    # Shell command
    shell_parser = subparsers.add_parser("shell", aliases=["sh"],
                                        help="Execute a shell command")
    shell_parser.add_argument("command", help="Shell command to execute")
    
    # Python execution
    py_parser = subparsers.add_parser("python", aliases=["py"],
                                      help="Execute Python code")
    py_parser.add_argument("code", help="Python code to execute")
    
    # File operations
    read_parser = subparsers.add_parser("read", help="Read a file")
    read_parser.add_argument("path", help="File path")
    read_parser.add_argument("--lines", "-n", type=int, default=100,
                            help="Number of lines to read")
    
    write_parser = subparsers.add_parser("write", help="Write a file")
    write_parser.add_argument("path", help="File path")
    write_parser.add_argument("content", help="Content to write")
    
    # Git operations
    git_parser = subparsers.add_parser("git", help="Git operations")
    git_parser.add_argument("args", nargs="+", help="Git arguments")
    
    # Queue operations
    queue_parser = subparsers.add_parser("queue", help="Task queue operations")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_cmd")
    
    queue_list_parser = queue_subparsers.add_parser("list", help="List queue")
    queue_add_parser = queue_subparsers.add_parser("add", help="Add task")
    queue_add_parser.add_argument("description", help="Task description")
    queue_add_parser.add_argument("--priority", "-p", default="normal",
                                 choices=["low", "normal", "high", "critical"])
    queue_run_parser = queue_subparsers.add_parser("run", help="Run queue")
    queue_run_parser.add_argument("--max", "-m", type=int, default=100,
                                 help="Max iterations")
    
    # Agent command
    agent_parser = subparsers.add_parser("agent", help="Run specific agent")
    agent_parser.add_argument("agent", choices=["architect", "coder", "tester", "fixer", "debator"])
    agent_parser.add_argument("task", help="Task for the agent")
    
    # Memory command
    memory_parser = subparsers.add_parser("memory", help="Memory operations")
    memory_parser.add_argument("cmd", choices=["stats"])
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show status")
    
    args = parser.parse_args()
    
    # Handle no command - show interactive mode
    if not args.command:
        cli = DevinCLI(workspace=args.workspace, verbose=args.verbose)
        cli.print_banner()
        
        print("Entering interactive mode. Type 'help' for commands, 'exit' to quit.")
        print()
        
        while True:
            try:
                prompt = input(colored("devin> ", Fore.CYAN))
                prompt = prompt.strip()
                
                if not prompt:
                    continue
                
                if prompt.lower() in ["exit", "quit", "q"]:
                    print(dim("Goodbye!"))
                    break
                
                if prompt.lower() == "help":
                    print(info("Available commands:"))
                    print("  status          - Show current status")
                    print("  execute <goal>  - Execute a goal")
                    print("  shell <cmd>     - Run shell command")
                    print("  python <code>   - Run Python code")
                    print("  read <path>     - Read file")
                    print("  write <path> <content> - Write file")
                    print("  git <args>      - Git operations")
                    print("  queue list      - List task queue")
                    print("  queue add <desc> - Add task")
                    print("  queue run       - Run queue")
                    print("  memory stats    - Memory statistics")
                    print("  exit            - Exit")
                    continue
                
                if prompt.lower() == "status":
                    cli.print_status()
                    continue
                
                if prompt.lower().startswith("execute "):
                    goal = prompt[8:].strip()
                    cli.cmd_execute(goal)
                    continue
                
                if prompt.lower().startswith("shell "):
                    cmd = prompt[6:].strip()
                    cli.cmd_shell(cmd)
                    continue
                
                if prompt.lower().startswith("python "):
                    code = prompt[7:].strip()
                    cli.cmd_python(code)
                    continue
                
                print(warning(f"Unknown command: {prompt}. Type 'help' for available commands."))
                
            except KeyboardInterrupt:
                print(dim("\nUse 'exit' to quit."))
            except EOFError:
                print(dim("\nGoodbye!"))
                break
        
        return 0
    
    # Handle commands
    cli = DevinCLI(workspace=args.workspace, verbose=args.verbose)
    
    if args.command in ["execute", "exec", "e"]:
        result = cli.cmd_execute(args.goal, args.workflow)
        return 0 if result.success else 1
    
    elif args.command in ["shell", "sh"]:
        result = cli.cmd_shell(args.command)
        return 0 if result.get("success") else 1
    
    elif args.command in ["python", "py"]:
        result = cli.cmd_python(args.code)
        return 0 if result.get("success") else 1
    
    elif args.command == "read":
        result = cli.cmd_read(args.path, args.lines)
        return 0 if result.get("success") else 1
    
    elif args.command == "write":
        result = cli.cmd_write(args.path, args.content)
        return 0 if result.get("success") else 1
    
    elif args.command == "git":
        result = cli.cmd_git(*args.args)
        return 0 if result.get("success") else 1
    
    elif args.command == "queue":
        if args.queue_cmd == "list" or not args.queue_cmd:
            cli.cmd_queue_list()
        elif args.queue_cmd == "add":
            cli.cmd_queue_add(args.description, args.priority)
        elif args.queue_cmd == "run":
            cli.cmd_queue_run(args.max)
        return 0
    
    elif args.command == "agent":
        result = cli.cmd_agent(args.agent, args.task)
        return 0 if result and result.success else 1
    
    elif args.command == "memory":
        if args.cmd == "stats":
            cli.cmd_memory_stats()
        return 0
    
    elif args.command == "status":
        cli.print_status()
        return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
