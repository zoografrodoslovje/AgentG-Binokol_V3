"""
Self-improvement module for the Devin Agent system.
Provides prompt optimization and learning from past experiences.
"""

import json
import time
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path

from .memory import JsonStore, MemoryEntry


class PromptOptimizer:
    """
    Optimizes prompts based on success/failure patterns.
    
    Learns from:
    - What prompts worked well for certain tasks
    - What prompts led to failures
    - Common patterns in successful executions
    """
    
    def __init__(self, memory_store: JsonStore):
        """
        Initialize the prompt optimizer.
        
        Args:
            memory_store: JsonStore instance for storing learnings
        """
        self.memory_store = memory_store
        self._patterns: Dict[str, List[str]] = {}
    
    def record_success(self, task: str, prompt: str, result: str):
        """
        Record a successful prompt for a task.
        
        Args:
            task: The task description
            prompt: The prompt that worked
            result: The result achieved
        """
        # Store in memory
        self.memory_store.add(
            content=json.dumps({
                "task": task,
                "prompt": prompt,
                "result": result[:500] if result else ""
            }),
            entry_type="learning",
            tags=["prompt", "success", task[:30]],
            importance=4
        )
        
        # Update patterns
        task_key = self._normalize_task_key(task)
        if task_key not in self._patterns:
            self._patterns[task_key] = []
        
        if prompt not in self._patterns[task_key]:
            self._patterns[task_key].append(prompt)
    
    def record_failure(self, task: str, prompt: str, error: str):
        """
        Record a failed prompt attempt.
        
        Args:
            task: The task description
            prompt: The prompt that failed
            error: The error that occurred
        """
        self.memory_store.add(
            content=json.dumps({
                "task": task,
                "prompt": prompt,
                "error": error
            }),
            entry_type="learning",
            tags=["prompt", "failure", task[:30]],
            importance=3
        )
    
    def get_optimized_prompt(self, task: str, base_prompt: str) -> str:
        """
        Get an optimized prompt for a task.
        
        Args:
            task: The task description
            base_prompt: The base prompt to optimize
            
        Returns:
            Optimized prompt
        """
        task_key = self._normalize_task_key(task)
        
        # Get successful patterns for similar tasks
        successful_prompts = self._get_successful_prompts(task)
        
        if not successful_prompts:
            return base_prompt
        
        # Analyze successful prompts for common elements
        common_elements = self._extract_common_elements(successful_prompts)
        
        if common_elements:
            return f"{base_prompt}\n\nOptimization: {' '.join(common_elements)}"
        
        return base_prompt
    
    def _normalize_task_key(self, task: str) -> str:
        """Normalize task description to a key."""
        # Remove common filler words and normalize
        words = task.lower().split()
        key_words = [w for w in words if len(w) > 3 and w not in [
            "the", "and", "for", "with", "this", "that", "from", "about"
        ]]
        return " ".join(key_words[:5])
    
    def _get_successful_prompts(self, task: str) -> List[str]:
        """Get previously successful prompts for similar tasks."""
        similar_entries = self.memory_store.search(task, max_results=10)
        
        prompts = []
        for entry in similar_entries:
            if entry.type == "learning":
                try:
                    data = json.loads(entry.content)
                    if "prompt" in data:
                        prompts.append(data["prompt"])
                except json.JSONDecodeError:
                    pass
        
        return prompts
    
    def _extract_common_elements(self, prompts: List[str]) -> List[str]:
        """Extract common elements from successful prompts."""
        if not prompts:
            return []
        
        # Simple approach: look for common phrases
        all_words = []
        for prompt in prompts:
            words = prompt.lower().split()
            all_words.extend([w for w in words if len(w) > 4])
        
        # Count word frequencies
        word_count: Dict[str, int] = {}
        for word in all_words:
            word_count[word] = word_count.get(word, 0) + 1
        
        # Get words that appear in multiple prompts
        common = []
        for word, count in word_count.items():
            if count >= len(prompts) // 2 and count >= 2:
                common.append(word)
        
        return common[:5]


class SelfImprove:
    """
    Main self-improvement system.
    
    Features:
    - Learns from task outcomes
    - Optimizes agent prompts over time
    - Maintains a knowledge base of improvements
    """
    
    def __init__(self, memory_store: JsonStore):
        """
        Initialize self-improvement system.
        
        Args:
            memory_store: JsonStore instance
        """
        self.memory_store = memory_store
        self.prompt_optimizer = PromptOptimizer(memory_store)
        self._improvements: List[Dict] = []
    
    def learn_from_task(self, task: str, agent_name: str,
                       prompt: str, success: bool,
                       result: str = "", error: str = ""):
        """
        Learn from a task execution.
        
        Args:
            task: The task that was executed
            agent_name: Which agent handled it
            prompt: The prompt used
            success: Whether it succeeded
            result: Result or error message
        """
        if success:
            self.prompt_optimizer.record_success(task, prompt, result)
            
            # Store improvement
            self.memory_store.add(
                content=json.dumps({
                    "task": task,
                    "agent": agent_name,
                    "pattern": prompt,
                    "improvement": result[:300]
                }),
                entry_type="learning",
                tags=["improvement", agent_name],
                importance=4
            )
        else:
            self.prompt_optimizer.record_failure(task, prompt, error)
    
    def get_improved_system_prompt(self, agent_name: str, base_prompt: str) -> str:
        """
        Get an improved system prompt based on learnings.
        
        Args:
            agent_name: Name of the agent
            base_prompt: Base system prompt
            
        Returns:
            Improved system prompt
        """
        # Get recent learnings for this agent
        entries = self.memory_store.get_recent(count=20)
        
        learnings = []
        for entry in entries:
            if entry.type == "learning" and agent_name in entry.tags:
                try:
                    data = json.loads(entry.content)
                    learnings.append(data)
                except json.JSONDecodeError:
                    pass
        
        if not learnings:
            return base_prompt
        
        # Build improvement notes
        improvements = []
        
        # Extract common success patterns
        successes = [l for l in learnings if "improvement" in l]
        if successes:
            improvements.append("Based on recent successes, consider these patterns:")
            for success in successes[:3]:
                if "pattern" in success:
                    improvements.append(f"- {success['pattern'][:100]}")
        
        if improvements:
            return f"{base_prompt}\n\nImprovements:\n" + "\n".join(improvements)
        
        return base_prompt
    
    def analyze_failures(self) -> Dict[str, Any]:
        """
        Analyze patterns in failures.
        
        Returns:
            Analysis results
        """
        entries = self.memory_store.get_recent(count=100)
        
        failures = []
        for entry in entries:
            if entry.type == "learning" and "failure" in entry.tags:
                try:
                    failures.append(json.loads(entry.content))
                except json.JSONDecodeError:
                    pass
        
        if not failures:
            return {"total_failures": 0, "patterns": []}
        
        # Analyze failure patterns
        error_types: Dict[str, int] = {}
        for failure in failures:
            error = failure.get("error", "unknown")
            # Extract error type
            error_type = error.split(":")[0] if ":" in error else error[:50]
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return {
            "total_failures": len(failures),
            "error_types": error_types,
            "patterns": [
                {"error": error, "count": count}
                for error, count in sorted(error_types.items(), key=lambda x: -x[1])
            ]
        }
    
    def suggest_improvements(self) -> List[str]:
        """
        Suggest areas for improvement.
        
        Returns:
            List of improvement suggestions
        """
        suggestions = []
        
        # Analyze failure patterns
        analysis = self.analyze_failures()
        
        if analysis["total_failures"] > 5:
            error_list = ', '.join(analysis['patterns'][i]['error'] for i in range(min(3, len(analysis['patterns']))))
            suggestions.append(
                f"Consider reviewing {analysis['total_failures']} recent failures. "
                f"Most common issues: {error_list}"
            )
        
        # Check for missing capabilities
        recent = self.memory_store.get_recent(count=20)
        agent_usage: Dict[str, int] = {}
        
        for entry in recent:
            for tag in entry.tags:
                if tag in ["architect", "coder", "tester", "fixer", "debator"]:
                    agent_usage[tag] = agent_usage.get(tag, 0) + 1
        
        # Suggest using other agents if some are underused
        for agent in ["architect", "debator"]:
            if agent_usage.get(agent, 0) < 2:
                suggestions.append(
                    f"Consider using the {agent} agent more - it can help catch issues early."
                )
        
        return suggestions


class LearningTracker:
    """Tracks learning progress and metrics."""
    
    def __init__(self, memory_store: JsonStore):
        """Initialize the learning tracker."""
        self.memory_store = memory_store
    
    def record_learning(self, category: str, content: str, tags: List[str]):
        """
        Record a learning entry.
        
        Args:
            category: Category of learning
            content: Content learned
            tags: Tags for organization
        """
        self.memory_store.add(
            content=content,
            entry_type="learning",
            tags=[category] + tags,
            importance=3
        )
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get learning statistics."""
        stats = self.memory_store.get_stats()
        
        # Get recent learning entries
        recent = self.memory_store.get_recent(count=50)
        learnings = [e for e in recent if e.type == "learning"]
        
        # Count by tag
        tag_counts: Dict[str, int] = {}
        for entry in learnings:
            for tag in entry.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        return {
            "total_learnings": len(learnings),
            "by_tag": tag_counts,
            "total_memory_entries": stats["total_entries"],
            "storage_path": stats["storage_path"]
        }
    
    def export_learnings(self, path: str) -> bool:
        """
        Export learnings to a file.
        
        Args:
            path: Path to export to
            
        Returns:
            Success status
        """
        try:
            learnings = self.memory_store.get_all()
            learnings = [e for e in learnings if e.type == "learning"]
            
            data = [e.to_dict() for e in learnings]
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            return True
        except Exception:
            return False
