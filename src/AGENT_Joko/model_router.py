"""
Model Router - Routes tasks to appropriate models based on complexity and type.
"""

import re
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .config import Config, get_config


class TaskComplexity(Enum):
    """Complexity levels for tasks."""
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class TaskType(Enum):
    """Types of tasks for routing."""
    ARCHITECTURE = "architecture"
    CODING = "coding"
    TESTING = "testing"
    DEBUGGING = "debugging"
    ANALYSIS = "analysis"
    GENERAL = "general"


@dataclass
class RoutedTask:
    """A task with routing information."""
    original_task: str
    task_type: TaskType
    complexity: TaskComplexity
    recommended_model: str
    reasoning: str
    enhanced_prompt: str

    def to_dict(self) -> dict:
        """Convert routing details to a JSON-safe dictionary."""
        return {
            "original_task": self.original_task,
            "task_type": self.task_type.value,
            "complexity": self.complexity.value,
            "recommended_model": self.recommended_model,
            "model": self.recommended_model,
            "reasoning": self.reasoning,
            "enhanced_prompt": self.enhanced_prompt,
        }


class ModelRouter:
    """Routes tasks to appropriate models based on analysis."""
    
    # Keywords that indicate different task types
    TASK_KEYWORDS = {
        TaskType.ARCHITECTURE: [
            "design", "architecture", "structure", "plan", "blueprint",
            "system design", "high-level", "architecture diagram",
            "component design", "module design", "interface"
        ],
        TaskType.CODING: [
            "write", "implement", "create", "code", "function",
            "class", "module", "feature", "develop", "build",
            "add", "modify", "refactor", "optimize"
        ],
        TaskType.TESTING: [
            "test", "validate", "verify", "check", "spec",
            "unit test", "integration test", "test case",
            "coverage", "assert", "quality"
        ],
        TaskType.DEBUGGING: [
            "fix", "debug", "error", "issue", "bug", "crash",
            "exception", "problem", "solve", "resolve",
            "repair", "patch", "hotfix"
        ],
        TaskType.ANALYSIS: [
            "analyze", "review", "examine", "understand",
            "investigate", "inspect", "evaluate", "assess"
        ],
    }
    
    # Keywords that indicate complexity
    HIGH_COMPLEXITY_KEYWORDS = [
        "complex", "difficult", "challenging", "advanced",
        "distributed", "concurrent", "parallel", "async",
        "machine learning", "ml", "ai", "neural", "deep learning",
        "database", "migration", "refactor", "scalable",
        "microservice", "api", "gateway", "architecture"
    ]
    
    MEDIUM_COMPLEXITY_KEYWORDS = [
        "feature", "module", "class", "function", "implement",
        "create", "build", "develop", "add", "integrate",
        "interface", "service", "handler", "controller"
    ]
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize the router with configuration."""
        self.config = config or get_config()
    
    def analyze_task(self, task: str) -> RoutedTask:
        """
        Analyze a task and determine routing.
        
        Args:
            task: The task description
            
        Returns:
            RoutedTask with routing information
        """
        task_lower = task.lower()
        
        # Determine task type
        task_type = self._determine_task_type(task_lower)
        
        # Determine complexity
        complexity = self._determine_complexity(task_lower)
        
        # Select appropriate model
        model = self._select_model(task_type, complexity)
        
        # Enhance prompt based on routing
        enhanced_prompt = self._enhance_prompt(task, task_type, complexity)
        
        reasoning = self._generate_reasoning(task_type, complexity, model)
        
        return RoutedTask(
            original_task=task,
            task_type=task_type,
            complexity=complexity,
            recommended_model=model,
            reasoning=reasoning,
            enhanced_prompt=enhanced_prompt
        )
    
    def _determine_task_type(self, task: str) -> TaskType:
        """Determine the type of task based on keywords."""
        scores = {}
        
        for task_type, keywords in self.TASK_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in task)
            scores[task_type] = score
        
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        return TaskType.GENERAL
    
    def _determine_complexity(self, task: str) -> TaskComplexity:
        """Determine task complexity based on keywords and patterns."""
        # Count high complexity indicators
        high_count = sum(1 for kw in self.HIGH_COMPLEXITY_KEYWORDS if kw in task)
        medium_count = sum(1 for kw in self.MEDIUM_COMPLEXITY_KEYWORDS if kw in task)
        
        # Check for code snippets or detailed specifications
        if re.search(r'```[\s\S]*?```', task):
            high_count += 2
        if re.search(r'\b\w+\.\w+\.\w+\b', task):  # e.g., module.submodule.component
            high_count += 1
        
        # Check for question marks and lists (might indicate simpler analysis)
        if '?' in task and high_count < 2:
            medium_count += 1
        if re.search(r'^\d+\.', task, re.MULTILINE):
            medium_count += 2
        
        # Determine complexity
        if high_count >= 2:
            return TaskComplexity.COMPLEX
        elif high_count >= 1 or medium_count >= 3:
            return TaskComplexity.MEDIUM
        else:
            return TaskComplexity.SIMPLE
    
    def _select_model(self, task_type: TaskType, complexity: TaskComplexity) -> str:
        """Select the appropriate model for the task."""
        # Map task types to agent configs
        agent_mapping = {
            TaskType.ARCHITECTURE: "architect",
            TaskType.CODING: "coder",
            TaskType.TESTING: "tester",
            TaskType.DEBUGGING: "fixer",
            TaskType.ANALYSIS: "debator",
            TaskType.GENERAL: "coder",
        }
        
        agent_name = agent_mapping.get(task_type, "coder")

        # Keep role-specialized routing stable. Complexity is handled by prompt/context.
        return self.config.get_model_for_agent(agent_name)
    
    def _enhance_prompt(self, task: str, task_type: TaskType, complexity: TaskComplexity) -> str:
        """Enhance the prompt based on routing context."""
        enhancements = []
        
        # Add context based on task type
        if task_type == TaskType.ARCHITECTURE:
            enhancements.append(
                "Consider: clean architecture principles, separation of concerns, "
                "scalability, maintainability, and proper module boundaries."
            )
        elif task_type == TaskType.CODING:
            enhancements.append(
                "Follow best practices: clean code, proper error handling, "
                "documentation, and modular structure."
            )
        elif task_type == TaskType.TESTING:
            enhancements.append(
                "Ensure comprehensive coverage: happy path, edge cases, "
                "error conditions, and proper assertions."
            )
        elif task_type == TaskType.DEBUGGING:
            enhancements.append(
                "Analyze the root cause carefully. Provide a minimal, "
                "targeted fix that resolves the issue without breaking existing functionality."
            )
        
        # Add complexity-based guidance
        if complexity == TaskComplexity.COMPLEX:
            enhancements.append(
                "This is a complex task. Break it down into smaller steps "
                "and address each component systematically."
            )
        elif complexity == TaskComplexity.SIMPLE:
            enhancements.append(
                "This appears to be a straightforward task. "
                "Implement it directly and concisely."
            )
        
        if enhancements:
            return f"{task}\n\nContext: {' '.join(enhancements)}"
        return task
    
    def _generate_reasoning(self, task_type: TaskType, complexity: TaskComplexity, model: str) -> str:
        """Generate reasoning explanation for routing decision."""
        return (
            f"Task type: {task_type.value}, "
            f"Complexity: {complexity.value}, "
            f"Routed to model: {model}"
        )
    
    def route(self, task: str) -> Tuple[str, str]:
        """
        Simple routing interface returning model and enhanced prompt.
        
        Returns:
            Tuple of (model_name, enhanced_prompt)
        """
        routed = self.analyze_task(task)
        return routed.recommended_model, routed.enhanced_prompt
