"""
Git operations tool for the Devin Agent system.
Provides git commit, rollback, status, and branch management.
"""

import subprocess
import json
import re
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime


class GitOps:
    """Git operations toolkit."""
    
    def __init__(self, repo_path: str = "."):
        """
        Initialize git operations.
        
        Args:
            repo_path: Path to the git repository
        """
        self.repo_path = Path(repo_path).resolve()
        self._git_dir = self.repo_path / ".git"
    
    def _run_git(self, *args, timeout: int = 30) -> Dict[str, Any]:
        """Run a git command."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Git command timed out"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def is_repo(self) -> bool:
        """Check if the path is a git repository."""
        return self._git_dir.exists() and self._git_dir.is_dir()
    
    def status(self, short: bool = False) -> Dict[str, Any]:
        """
        Get git status.
        
        Args:
            short: Use short format
            
        Returns:
            Dictionary with status info
        """
        # Always use porcelain for machine parsing; optionally also include the human-readable form.
        porcelain = self._run_git("status", "--porcelain")
        if not porcelain["success"]:
            return porcelain

        human = None
        if not short:
            human = self._run_git("status")

        lines = porcelain["stdout"].split("\n") if porcelain["stdout"] else []
        files = []
        
        for line in lines:
            if len(line) >= 3:
                index_status = line[0].strip()
                worktree_status = line[1].strip()
                file_path = line[3:].strip()
                
                files.append({
                    "index_status": index_status,
                    "worktree_status": worktree_status,
                    "path": file_path
                })
        
        # Get current branch
        branch_result = self._run_git("branch", "--show-current")
        current_branch = branch_result.get("stdout", "") if branch_result["success"] else ""
        
        # Get staged files summary
        staged_count = len([f for f in files if f["index_status"]])
        unstaged_count = len([f for f in files if f["worktree_status"]])
        
        return {
            "success": True,
            "is_repo": self.is_repo(),
            "current_branch": current_branch,
            "files": files,
            "staged_count": staged_count,
            "unstaged_count": unstaged_count,
            "clean": len(files) == 0,
            "stdout": (
                human.get("stdout") if isinstance(human, dict) and human.get("success") else None
            )
            if not short
            else porcelain["stdout"],
            "stderr": (
                human.get("stderr") if isinstance(human, dict) and human.get("success") else None
            )
            if not short
            else porcelain.get("stderr"),
        }
    
    def add(self, patterns: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Stage files.
        
        Args:
            patterns: File patterns to stage (default: all)
            
        Returns:
            Dictionary with result
        """
        if patterns is None:
            result = self._run_git("add", "-A")
        else:
            args = ["add"] + patterns
            result = self._run_git(*args)
        
        return result
    
    def commit(self, message: str, allow_empty: bool = False) -> Dict[str, Any]:
        """
        Create a commit.
        
        Args:
            message: Commit message
            allow_empty: Allow empty commit
            
        Returns:
            Dictionary with result
        """
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        
        result = self._run_git(*args)
        
        if result["success"]:
            # Get the commit hash
            hash_result = self._run_git("rev-parse", "HEAD")
            commit_hash = hash_result.get("stdout", "")[:8] if hash_result["success"] else ""
            
            result["commit_hash"] = commit_hash
            result["message"] = message
        
        return result
    
    def log(self, max_count: int = 10, format_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Get commit log.
        
        Args:
            max_count: Maximum number of commits to show
            format_str: Custom format string
            
        Returns:
            Dictionary with log entries
        """
        if format_str is None:
            format_str = "%h|%s|%an|%ad"
        
        result = self._run_git("log", f"--max-count={max_count}", f"--format={format_str}")
        
        if not result["success"]:
            return result
        
        entries = []
        for line in result["stdout"].split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4:
                    entries.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3]
                    })
        
        return {
            "success": True,
            "commits": entries
        }
    
    def diff(self, file: Optional[str] = None, staged: bool = False,
             cached: bool = False) -> Dict[str, Any]:
        """
        Show diff.
        
        Args:
            file: Specific file to diff
            staged: Show staged changes
            cached: Alias for staged
            
        Returns:
            Dictionary with diff output
        """
        args = ["diff"]
        if staged or cached:
            args.append("--cached")
        if file:
            args.append("--")
            args.append(file)
        
        result = self._run_git(*args)
        
        return result
    
    def checkout(self, target: str, create_branch: bool = False) -> Dict[str, Any]:
        """
        Checkout a branch or commit.
        
        Args:
            target: Target branch or commit
            create_branch: Create a new branch
            
        Returns:
            Dictionary with result
        """
        args = ["checkout"]
        if create_branch:
            args.append("-b")
        args.append(target)
        
        result = self._run_git(*args)
        return result
    
    def branch(self, name: Optional[str] = None, delete: bool = False,
               list_branches: bool = False) -> Dict[str, Any]:
        """
        Manage branches.
        
        Args:
            name: Branch name
            delete: Delete a branch
            list_branches: List all branches
            
        Returns:
            Dictionary with result
        """
        args = ["branch"]
        
        if delete:
            args.append("-d")
            args.append(name)
        elif list_branches:
            args.append("-a")
        elif name:
            args.append(name)
        else:
            args.append("-a")
        
        result = self._run_git(*args)
        
        if list_branches and result["success"]:
            branches = [b.strip() for b in result["stdout"].split("\n") if b]
            result["branches"] = branches
        
        return result
    
    def reset(self, target: str, hard: bool = False) -> Dict[str, Any]:
        """
        Reset to a target commit.
        
        Args:
            target: Target commit (HEAD~, commit hash, etc.)
            hard: Use --hard flag
            
        Returns:
            Dictionary with result
        """
        args = ["reset"]
        if hard:
            args.append("--hard")
        args.append(target)
        
        return self._run_git(*args)
    
    def rollback(self, steps: int = 1) -> Dict[str, Any]:
        """
        Rollback commits (revert).
        
        Args:
            steps: Number of commits to rollback
            
        Returns:
            Dictionary with result
        """
        # Get current HEAD
        head_result = self._run_git("rev-parse", "HEAD")
        if not head_result["success"]:
            return head_result
        
        current_hash = head_result["stdout"]
        
        # Create revert commits for each step
        for _ in range(steps):
            result = self._run_git("revert", "--no-commit", "HEAD")
            if result["success"]:
                # Create the revert commit
                self._run_git("commit", "-m", f"Revert to previous state")
        
        return {
            "success": True,
            "rolled_back": steps,
            "message": f"Rolled back {steps} commit(s)"
        }
    
    def hard_reset(self, target: str) -> Dict[str, Any]:
        """
        Hard reset to a target (use with caution).
        
        Args:
            target: Target commit
            
        Returns:
            Dictionary with result
        """
        return self._run_git("reset", "--hard", target)
    
    def get_current_commit(self) -> Dict[str, Any]:
        """Get the current commit hash."""
        result = self._run_git("rev-parse", "HEAD")
        
        if result["success"]:
            return {
                "success": True,
                "hash": result["stdout"],
                "short_hash": result["stdout"][:8]
            }
        return result
    
    def stash(self, message: Optional[str] = None, pop: bool = False,
              apply: bool = False) -> Dict[str, Any]:
        """
        Stash changes.
        
        Args:
            message: Stash message
            pop: Pop the stash
            apply: Apply the stash without removing
            
        Returns:
            Dictionary with result
        """
        if pop:
            return self._run_git("stash", "pop")
        elif apply:
            return self._run_git("stash", "apply")
        else:
            args = ["stash", "push"]
            if message:
                args.extend(["-m", message])
            return self._run_git(*args)
    
    def get_remote_info(self) -> Dict[str, Any]:
        """Get information about remotes."""
        result = self._run_git("remote", "-v")
        
        if result["success"]:
            remotes = {}
            for line in result["stdout"].split("\n"):
                if line:
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        url = parts[1]
                        if name not in remotes:
                            remotes[name] = {"fetch": None, "push": None}
                        if "(fetch)" in line:
                            remotes[name]["fetch"] = url
                        if "(push)" in line:
                            remotes[name]["push"] = url
            
            return {
                "success": True,
                "remotes": remotes
            }
        return result
    
    def auto_commit(self, message: str) -> Dict[str, Any]:
        """
        Stage all changes and commit.
        
        Args:
            message: Commit message
            
        Returns:
            Dictionary with result
        """
        # Stage all changes
        add_result = self.add()
        if not add_result["success"]:
            return add_result
        
        # Check if there's anything to commit
        status = self.status(short=True)
        if status.get("staged_count", 0) == 0:
            return {
                "success": False,
                "error": "No changes to commit"
            }
        
        # Commit
        return self.commit(message)


class GitBranch:
    """Git branch context manager for safe branch operations."""
    
    def __init__(self, git_ops: GitOps, branch_name: str, base_branch: str = "main"):
        """
        Initialize branch context.
        
        Args:
            git_ops: GitOps instance
            branch_name: Name for the new branch
            base_branch: Base branch to create from
        """
        self.git_ops = git_ops
        self.branch_name = branch_name
        self.base_branch = base_branch
        self.previous_branch: Optional[str] = None
    
    def __enter__(self):
        """Switch to the new branch."""
        # Get current branch
        status = self.git_ops.status()
        self.previous_branch = status.get("current_branch", "")
        
        # Create and switch to new branch
        self.git_ops.checkout(self.base_branch)
        result = self.git_ops.checkout(self.branch_name, create_branch=True)
        
        if not result["success"]:
            # Branch might already exist, just switch
            self.git_ops.checkout(self.branch_name)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Return to previous branch."""
        if self.previous_branch:
            self.git_ops.checkout(self.previous_branch)
        
        return False  # Don't suppress exceptions
