"""
Task Queue for the Devin Agent system.
Manages autonomous task execution and tracking.
"""

import time
import json
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority levels for tasks."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    """A task in the queue."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "dependencies": self.dependencies,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Create from dictionary."""
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])
        return cls(**data)
    
    def mark_started(self):
        """Mark task as started."""
        self.status = TaskStatus.IN_PROGRESS
        self.started_at = time.time()
    
    def mark_completed(self, result: str):
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.result = result
    
    def mark_failed(self, error: str):
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = time.time()
    
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.retry_count < self.max_retries
    
    def increment_retry(self):
        """Increment retry count."""
        self.retry_count += 1
        self.status = TaskStatus.PENDING


class TaskQueue:
    """
    Task queue for managing autonomous task execution.
    
    Features:
    - Priority-based ordering
    - Dependency management
    - Retry logic
    - Persistence to disk
    - Progress tracking
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize the task queue.
        
        Args:
            storage_path: Path to store task queue state
        """
        if storage_path:
            self.storage_path = Path(storage_path).expanduser()
        else:
            # Default to a project-local queue file to avoid home-dir permission issues
            # and to keep runs portable under Pinokio.
            self.storage_path = Path.cwd() / ".devin_agent" / "task_queue.json"
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._tasks: Dict[str, Task] = {}
        self._load()
    
    def _load(self):
        """Load tasks from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for task_data in data.get("tasks", []):
                    task = Task.from_dict(task_data)
                    self._tasks[task.id] = task
            except (json.JSONDecodeError, KeyError):
                self._tasks = {}
    
    def _save(self):
        """Save tasks to disk."""
        data = {
            "saved_at": time.time(),
            "tasks": [task.to_dict() for task in self._tasks.values()]
        }
        
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def add(self, description: str, priority: TaskPriority = TaskPriority.NORMAL,
            dependencies: Optional[List[str]] = None,
            metadata: Optional[Dict[str, Any]] = None) -> Task:
        """
        Add a new task to the queue.
        
        Args:
            description: Task description
            priority: Task priority
            dependencies: IDs of tasks that must complete first
            metadata: Additional metadata
            
        Returns:
            The created Task
        """
        task = Task(
            id=str(uuid.uuid4())[:8],
            description=description,
            priority=priority,
            dependencies=dependencies or [],
            metadata=metadata or {}
        )
        
        self._tasks[task.id] = task
        self._save()
        
        return task
    
    def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def remove(self, task_id: str) -> bool:
        """Remove a task from the queue."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save()
            return True
        return False
    
    def update(self, task: Task):
        """Update a task."""
        self._tasks[task.id] = task
        self._save()
    
    def get_next_task(self) -> Optional[Task]:
        """
        Get the next task that's ready to execute.
        
        A task is ready if:
        - Status is PENDING
        - All dependencies are COMPLETED
        
        Returns:
            Next task or None
        """
        pending = []
        
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            
            # Check dependencies
            deps_satisfied = all(
                self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self._tasks
            )
            
            if deps_satisfied:
                pending.append(task)
        
        if not pending:
            return None
        
        # Sort by priority (highest first) then by creation time (oldest first)
        pending.sort(key=lambda t: (-t.priority.value, t.created_at))
        
        return pending[0]
    
    def get_all(self, status: Optional[TaskStatus] = None) -> List[Task]:
        """
        Get all tasks, optionally filtered by status.
        
        Args:
            status: Optional status filter
            
        Returns:
            List of tasks
        """
        tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        # Sort by priority and creation time
        tasks.sort(key=lambda t: (-t.priority.value, t.created_at))
        
        return tasks
    
    def get_pending(self) -> List[Task]:
        """Get all pending tasks."""
        return self.get_all(status=TaskStatus.PENDING)
    
    def get_completed(self) -> List[Task]:
        """Get all completed tasks."""
        return self.get_all(status=TaskStatus.COMPLETED)
    
    def get_failed(self) -> List[Task]:
        """Get all failed tasks."""
        return self.get_all(status=TaskStatus.FAILED)
    
    def mark_started(self, task_id: str) -> bool:
        """Mark a task as started."""
        task = self.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.mark_started()
            self._save()
            return True
        return False
    
    def mark_completed(self, task_id: str, result: str):
        """Mark a task as completed."""
        task = self.get(task_id)
        if task:
            task.mark_completed(result)
            self._save()
    
    def mark_failed(self, task_id: str, error: str):
        """Mark a task as failed."""
        task = self.get(task_id)
        if task:
            task.mark_failed(error)
            self._save()
    
    def retry_task(self, task_id: str) -> bool:
        """Retry a failed task."""
        task = self.get(task_id)
        if task and task.can_retry():
            task.increment_retry()
            self._save()
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or blocked task."""
        task = self.get(task_id)
        if not task:
            return False
        if task.status not in {TaskStatus.PENDING, TaskStatus.BLOCKED}:
            return False
        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()
        self._save()
        return True

    def dependencies_satisfied(self, task_id: str) -> bool:
        """Return whether all dependencies for a task are completed."""
        task = self.get(task_id)
        if not task:
            return False
        return all(
            self._tasks[dep_id].status == TaskStatus.COMPLETED
            for dep_id in task.dependencies
            if dep_id in self._tasks
        )
    
    def clear_completed(self):
        """Clear all completed tasks."""
        to_remove = [
            task_id for task_id, task in self._tasks.items()
            if task.status == TaskStatus.COMPLETED
        ]
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        self._save()
    
    def clear_all(self):
        """Clear all tasks."""
        self._tasks = {}
        self._save()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        stats = {
            "total": len(self._tasks),
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
            "blocked": 0
        }
        
        for task in self._tasks.values():
            stats[task.status.value] = stats.get(task.status.value, 0) + 1
        
        stats["can_proceed"] = self.get_next_task() is not None
        
        return stats
    
    def get_summary(self) -> str:
        """Get a human-readable summary."""
        stats = self.get_stats()
        
        lines = [
            f"Task Queue Summary:",
            f"  Total: {stats['total']}",
            f"  Pending: {stats['pending']}",
            f"  In Progress: {stats['in_progress']}",
            f"  Completed: {stats['completed']}",
            f"  Failed: {stats['failed']}",
            f"  Blocked: {stats['blocked']}",
        ]
        
        return "\n".join(lines)


class TaskRunner:
    """Executes tasks from a queue."""
    
    def __init__(self, queue: TaskQueue, executor):
        """
        Initialize the task runner.
        
        Args:
            queue: TaskQueue instance
            executor: Callable that takes a task and returns a result
        """
        self.queue = queue
        self.executor = executor
        self.running = False
        self._current_task: Optional[Task] = None
    
    def run_next(self) -> Optional[Task]:
        """Run the next available task."""
        task = self.queue.get_next_task()
        
        if not task:
            return None
        
        self._current_task = task
        self.queue.mark_started(task.id)
        
        try:
            result = self.executor(task)
            self.queue.mark_completed(task.id, str(result))
            return task
        except Exception as e:
            error_msg = f"Execution failed: {str(e)}"
            
            if task.can_retry():
                self.queue.retry_task(task.id)
                task = self.queue.get(task.id)
            else:
                self.queue.mark_failed(task.id, error_msg)
            
            self._current_task = None
            return task
    
    def run_until_complete(self, max_iterations: int = 100,
                          delay: float = 1.0) -> Dict[str, Any]:
        """
        Run tasks until queue is empty or max iterations reached.
        
        Args:
            max_iterations: Maximum number of tasks to process
            delay: Delay between tasks
            
        Returns:
            Summary of run
        """
        self.running = True
        results = {
            "completed": 0,
            "failed": 0,
            "iterations": 0
        }
        
        for i in range(max_iterations):
            if not self.running:
                break
            
            task = self.run_next()
            
            if not task:
                break
            
            results["iterations"] += 1
            
            if task.status == TaskStatus.COMPLETED:
                results["completed"] += 1
            elif task.status == TaskStatus.FAILED:
                results["failed"] += 1
            
            if delay > 0:
                time.sleep(delay)
        
        self.running = False
        return results
    
    def stop(self):
        """Stop the runner."""
        self.running = False
