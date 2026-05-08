"""
Main orchestrator for the Devin Agent system.
Coordinates all agents, tools, and processes.
"""

import time
import json
import traceback
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path

from .config import Config, get_config
from .agents import (
    BaseAgent, AgentResponse,
    ArchitectAgent, CoderAgent, TesterAgent,
    FixerAgent, DebatorAgent
)
from .tools import FileOps, ShellTool, GitOps
from .memory import JsonStore, ContextManager
from .model_router import ModelRouter, TaskType, TaskComplexity
from .task_queue import TaskQueue, TaskStatus, TaskPriority, Task
from .self_improve import SelfImprove


class ExecutionResult:
    """Result of an execution step."""
    
    def __init__(self, success: bool, message: str = "",
                 data: Any = None, error: Optional[str] = None,
                 agent_name: Optional[str] = None):
        self.success = success
        self.message = message
        self.data = data
        self.error = error
        self.agent_name = agent_name
        self.timestamp = time.time()
    
    def __str__(self):
        if self.success:
            return f"✓ {self.message}"
        else:
            return f"✗ {self.message}: {self.error}"
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "agent_name": self.agent_name,
            "timestamp": self.timestamp
        }


class Orchestrator:
    """
    Main orchestrator for the Devin Agent system.
    
    Coordinates:
    - Multi-agent workflow (architect → coder → tester → fixer)
    - Tool execution
    - Git operations
    - Memory and context
    - Self-healing loops
    - Task queue management
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        session_id: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            config: Configuration (uses default if not provided)
            session_id: Session identifier
        """
        self.config = config or get_config()
        self.session_id = session_id or f"session_{int(time.time())}"
        self._event_callback = event_callback
        
        # Initialize components
        storage_path = self.config.memory.storage_path
        self.memory_store = JsonStore(
            storage_path=storage_path,
            max_entries=self.config.memory.max_entries
        )
        self.context_manager = ContextManager(
            memory_store=self.memory_store,
            context_window=self.config.memory.context_window
        )
        
        # Initialize tools
        self.file_ops = FileOps(workspace_root=self.config.workspace_root)
        self.shell_tool = ShellTool(workspace_root=self.config.workspace_root)
        self.git_ops = GitOps(repo_path=self.config.workspace_root)
        
        # Initialize model router
        self.router = ModelRouter(self.config)
        
        # Initialize agents
        self._agents: Dict[str, BaseAgent] = {}
        self._init_agents()
        
        # Initialize task queue
        self.task_queue = TaskQueue()
        
        # Initialize self-improvement
        self.self_improve = SelfImprove(self.memory_store)
        
        # Execution state
        self.running = False
        self._current_task: Optional[Task] = None
        self._execution_history: List[ExecutionResult] = []
        self._ollama_health_cache: Optional[Dict[str, Any]] = None
        self._ollama_health_cache_ts: float = 0.0
        self._warmup_status: Dict[str, Any] = {
            "enabled": bool(getattr(self.config, "model_warmup_enabled", False)),
            "started": False,
            "finished": False,
            "results": [],
        }
        self._seed_swarm_memory()
        if getattr(self.config, "model_warmup_enabled", False):
            self._run_model_warmup()

    _HEAL_REVIEWERS = {
        "architect": ["debator", "coder", "tester"],
        "coder": ["tester", "debator", "architect"],
        "tester": ["coder", "debator", "architect"],
        "fixer": ["debator", "coder", "tester"],
        "debator": ["architect", "coder", "tester"],
    }
    _SWARM_MEMORY_CORE_TAG = "swarm_core_v1"
    _SWARM_MEMORY_SCHEMA_TAG = "swarm_memory_schema_v1"
    _SCRAPER_MEMORY_TAG = "scraper_csv_schema_v1"
    _SWARM_ROLE_TAGS = {
        "architect": "swarm_role_architect_v1",
        "coder": "swarm_role_coder_v1",
        "tester": "swarm_role_tester_v1",
        "fixer": "swarm_role_fixer_v1",
        "debator": "swarm_role_debator_v1",
    }

    def _seed_swarm_memory(self) -> None:
        """Seed persistent memory with core swarm protocol and role triggers."""
        try:
            if not self.memory_store.get_by_tag(self._SWARM_MEMORY_CORE_TAG):
                self.memory_store.add(
                    content=(
                        "[CORE DIRECTIVE]\n"
                        "You are part of a 5-agent Autonomous AI Engineering Swarm.\n"
                        "Primary language: Python.\n"
                        "Verify dependencies instead of hallucinating them.\n"
                        "Role map: architect=design, coder=implementation, tester=validation, "
                        "fixer=debugging, debator=critical review."
                    ),
                    entry_type="memory_profile",
                    tags=["swarm", "core", self._SWARM_MEMORY_CORE_TAG],
                    metadata={"source": "bootstrap", "version": "v1"},
                    importance=5,
                )
            if not self.memory_store.get_by_tag(self._SWARM_MEMORY_SCHEMA_TAG):
                self.memory_store.add(
                    content=(
                        "[SWARM MEMORY SCHEMA]\n"
                        "Shared state keys: task, architect, coder, tester, fixer, debator, "
                        "critical_failures, iteration, max_iterations, final.\n"
                        "Behavior: task is immutable user intent; architect stores the technical "
                        "blueprint; coder stores the current implementation; tester stores the audit "
                        "report and extracts critical_failures; fixer stores targeted repair context; "
                        "debator stores adversarial review; iteration/max_iterations bound repair loops; "
                        "final stores the final recommendation.\n"
                        "Operational rules: preserve architectural intent across handoffs, refresh "
                        "critical_failures after each test cycle, keep memory cumulative where useful "
                        "but replace stale candidate outputs, and prefer durable, typed, explicit state "
                        "updates over implicit conversational drift."
                    ),
                    entry_type="memory_profile",
                    tags=["swarm", "schema", self._SWARM_MEMORY_SCHEMA_TAG],
                    metadata={"source": "bootstrap", "version": "v1"},
                    importance=5,
                )
            if not self.memory_store.get_by_tag(self._SCRAPER_MEMORY_TAG):
                self.memory_store.add(
                    content=(
                        "[SCRAPER CSV DIRECTIVE]\n"
                        "When creating a Python scraper script, prefer an immediately runnable requests-based script with retries, timeout handling, progress logging, and csv.DictWriter output.\n"
                        "Use this CSV field order unless the user explicitly overrides it.\n"
                        "Primary business fields: First Name, Last Name, Title, Cleaned Title, Uncleaned Company Name, Cleaned Company Name, Unverified Email, quality, result, free, role, Seniority, Departments, Mobile Phone, # Employees, Industry, Cleaned Industry, Keywords, Person Linkedin Url, Website, Company Linkedin Url, Facebook Url, Twitter Url, Company Address, SEO Description, Technologies, Annual Revenue, Total Funding, Latest Funding, Latest Funding Amount, Retail Locations, LinkedIn Group, LinkedIn Follow, headline, org_id, State, City, org_founded_year, org_city, org_country, industry_tag_id, postal_code, org_state, org_street_address.\n"
                        "Restaurant fields to append after the business fields: camis, name, boro, building, street, zipcode, phone, cuisine, inspection_date, grade, score.\n"
                        "If a source does not provide some columns, keep them in the CSV and write blank strings for missing values."
                    ),
                    entry_type="memory_profile",
                    tags=["scraper", "csv", "schema", self._SCRAPER_MEMORY_TAG],
                    metadata={"source": "bootstrap", "version": "v1"},
                    importance=5,
                )

            role_memories = {
                "architect": (
                    "Read task as the immutable anchor. Write the architect state as the contract for "
                    "data flow, security boundaries, credential handling, and implementation phases."
                ),
                "coder": (
                    "Read task and architect state first. Write coder state as the current candidate "
                    "implementation while preserving the blueprint and defensive programming constraints."
                ),
                "tester": (
                    "Read the latest candidate from fixer or coder. Write tester state as the audit "
                    "report and refresh critical_failures with concrete blockers, malformed input cases, "
                    "timeout handling, and 403/429 findings."
                ),
                "fixer": (
                    "Read task, architect, tester, critical_failures, and the latest candidate. Write "
                    "fixer state as minimal local patches, increment iteration, and preserve architecture."
                ),
                "debator": (
                    "Read the accepted candidate plus prior state. Write debator/final review focused on "
                    "maintenance risk, ethical concerns, OPSEC, and hidden failure modes."
                ),
            }
            for agent_name, content in role_memories.items():
                role_tag = self._SWARM_ROLE_TAGS[agent_name]
                if self.memory_store.get_by_tag(role_tag):
                    continue
                self.memory_store.add(
                    content=f"[ROLE MEMORY] {agent_name}: {content}",
                    entry_type="memory_profile",
                    tags=["swarm", "role", agent_name, role_tag],
                    metadata={"source": "bootstrap", "agent": agent_name, "version": "v1"},
                    importance=4,
                )
        except Exception:
            # Memory bootstrap should never block orchestration.
            pass

    def _emit(self, event_type: str, message: str, **extra: Any) -> None:
        """Emit an execution event to the optional callback."""
        if not self._event_callback:
            return
        try:
            payload: Dict[str, Any] = {
                "ts": time.time(),
                "type": event_type,
                "message": message,
                "session_id": self.session_id,
            }
            payload.update(extra)
            self._event_callback(payload)
        except Exception:
            # Events should never break execution.
            pass

    @staticmethod
    def _stringify_payload(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            try:
                return json.dumps(payload, indent=2)
            except Exception:
                return str(payload)
        return str(payload)

    @classmethod
    def _response_text(cls, response: Any) -> str:
        if response is None:
            return ""
        if hasattr(response, "data"):
            return cls._stringify_payload(getattr(response, "data"))
        if hasattr(response, "content"):
            return cls._stringify_payload(getattr(response, "content"))
        return cls._stringify_payload(response)

    def _healing_reviewers_for(self, agent_name: str) -> List[str]:
        reviewers = self._HEAL_REVIEWERS.get(agent_name, ["debator", "coder", "tester", "architect"])
        return [name for name in reviewers if name in self._agents and name != agent_name and name != "fixer"]

    def _healing_timeout_seconds(self) -> int:
        configured = getattr(self.config, "ollama_healing_timeout_seconds", None)
        default_timeout = getattr(self.config, "ollama_timeout_seconds", 60)
        timeout = configured if configured is not None else min(default_timeout, 25)
        return max(5, int(timeout))

    def _healing_max_tokens(self) -> int:
        configured = getattr(self.config, "ollama_healing_max_tokens", 1024)
        return max(128, int(configured))

    def _healing_fallback_models(self, primary_model: Optional[str] = None) -> List[str]:
        fallbacks = list(getattr(self.config, "ollama_fallback_models", []) or [])
        fast = []
        slow = []
        for model_name in fallbacks:
            if not model_name or model_name == primary_model:
                continue
            lowered = model_name.lower()
            if "qwen" in lowered:
                slow.append(model_name)
            else:
                fast.append(model_name)
        # Healing should fail fast and avoid the slow qwen fallback path.
        return fast

    def _call_agent_quick_process(
        self,
        agent: BaseAgent,
        task: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> AgentResponse:
        if hasattr(agent, "quick_process"):
            return agent.quick_process(
                task,
                max_tokens=max_tokens,
                timeout_seconds=self._healing_timeout_seconds(),
                fallback_models=self._healing_fallback_models(getattr(agent.agent_config, "model", None)),
                temperature=temperature,
            )
        return agent.process(task)
    
    def _init_agents(self):
        """Initialize all agents."""
        agent_classes = {
            "architect": ArchitectAgent,
            "coder": CoderAgent,
            "tester": TesterAgent,
            "fixer": FixerAgent,
            "debator": DebatorAgent
        }
        
        for name, agent_class in agent_classes.items():
            self._agents[name] = agent_class(self.config, self.session_id)

    def _warmup_models(self) -> List[str]:
        models: List[str] = []
        seen = set()
        for model_ref in (getattr(self.config, "models", {}) or {}).values():
            if not model_ref or model_ref in seen:
                continue
            seen.add(model_ref)
            models.append(model_ref)
        for model_ref in getattr(self.config, "ollama_fallback_models", []) or []:
            if not model_ref or model_ref in seen:
                continue
            seen.add(model_ref)
            models.append(model_ref)
        return models

    def _run_model_warmup(self) -> None:
        self._warmup_status["started"] = True
        try:
            models = self._warmup_models()
            if not models:
                self._warmup_status["results"] = []
                return
            self._emit("warmup", "Model warmup started", models=models)
            client = next(iter(self._agents.values())).ollama if self._agents else None
            if client is None:
                self._warmup_status["results"] = [{"success": False, "error": "No agents available for warmup"}]
            else:
                self._warmup_status["results"] = client.warmup(
                    models=models,
                    prompt=getattr(self.config, "model_warmup_prompt", "Reply with OK only."),
                    timeout_seconds=getattr(self.config, "model_warmup_timeout_seconds", 20),
                )
            self._emit("warmup", "Model warmup finished", results=self._warmup_status["results"])
        except Exception as e:
            self._warmup_status["results"] = [{"success": False, "error": str(e)}]
            self._emit("warmup", "Model warmup failed", error=str(e))
        finally:
            self._warmup_status["finished"] = True
    
    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Get an agent by name."""
        return self._agents.get(name)
    
    def execute_goal(self, goal: str, workflow: Optional[str] = None) -> ExecutionResult:
        """
        Execute a goal through the multi-agent workflow.
        
        Args:
            goal: The goal/requirement to accomplish
            workflow: Optional workflow specification (default: standard)
            
        Returns:
            ExecutionResult with the outcome
        """
        self.running = True
        start_time = time.time()
        self._emit("orchestrator", "Goal execution started", workflow=workflow, goal_preview=goal[:200])
        
        try:
            # Route the task
            routed = self.router.analyze_task(goal)
            self._emit(
                "routing",
                routed.reasoning,
                task_type=routed.task_type.value,
                complexity=routed.complexity.value,
                model=routed.recommended_model,
            )
            
            # Log the routing decision
            self.memory_store.add(
                content=f"Goal: {goal[:100]}\nRouting: {routed.reasoning}",
                entry_type="execution",
                tags=["goal", "routing"],
                importance=4
            )
            
            # Execute based on workflow
            if workflow == "debate_only":
                result = self._execute_debate(goal)
            elif workflow == "code_only":
                result = self._execute_coding(goal)
            elif workflow == "full":
                result = self._execute_full_workflow(goal, routed)
            else:
                # Auto-select based on task type
                if routed.task_type == TaskType.ARCHITECTURE:
                    result = self._execute_architecture(goal)
                elif routed.task_type == TaskType.DEBUGGING:
                    result = self._execute_debug_fix(goal)
                else:
                    result = self._execute_full_workflow(goal, routed)
            
            # Git auto-commit if enabled
            if self.config.git.auto_commit and result.success:
                self._auto_git_commit(goal, result)
            
            elapsed = time.time() - start_time
            result.message = f"{result.message} (completed in {elapsed:.1f}s)"
            self._emit("orchestrator", "Goal execution finished", success=result.success, elapsed_s=elapsed)
            
            return result
            
        except Exception as e:
            self._emit("error", f"Goal execution failed: {str(e)}")
            return ExecutionResult(
                success=False,
                message="Goal execution failed",
                error=str(e),
                agent_name="orchestrator"
            )
        finally:
            self.running = False
    
    def _execute_full_workflow(self, goal: str, routed) -> ExecutionResult:
        """
        Execute the full multi-agent workflow.
        
        Steps:
        1. Architect: Design the solution
        2. Coder: Implement the code
        3. Tester: Test the implementation
        4. Fixer: Fix any issues (if needed)
        """
        results = []
        
        # Step 1: Architecture
        self._emit("step", "Architect: plan", agent="architect")
        architect_result = self._execute_with_healing(
            "architect",
            goal,
            lambda: self._agents["architect"].process(routed.enhanced_prompt)
        )
        
        if not architect_result.success:
            return architect_result
        results.append(("architect", architect_result))
        
        # Step 2: Coding
        self._emit("step", "Coder: implement", agent="coder")
        architect_content = self._response_text(architect_result)
        coder_result = self._execute_with_healing(
            "coder",
            f"Implement based on this architecture:\n{architect_content}\n\nGoal: {goal}",
            lambda: self._agents["coder"].process(f"Implement this plan:\n{architect_content}")
        )
        
        if not coder_result.success:
            return coder_result
        results.append(("coder", coder_result))
        
        # Step 3: Testing
        self._emit("step", "Tester: validate", agent="tester")
        coder_content = self._response_text(coder_result)
        tester_result = self._execute_with_healing(
            "tester",
            f"Test the implementation for: {goal}",
            lambda: self._agents["tester"].process(f"Test this code/implementation:\n{coder_content}")
        )
        results.append(("tester", tester_result))
        
        # Step 4: Fixing (if tests failed)
        if not tester_result.success:
            self._emit("step", "Fixer: debug", agent="fixer")
            fix_result = self._execute_with_healing(
                "fixer",
                f"Fix issues found in testing",
                lambda: self._agents["fixer"].process(
                    f"Fix these issues:\n{tester_result.error or self._response_text(tester_result)}"
                )
            )
            results.append(("fixer", fix_result))
            
            if not fix_result.success:
                return fix_result
        
        # Compile results
        all_content = []
        for agent_name, result in results:
            all_content.append(f"=== {agent_name.upper()} ===\n{self._response_text(result)}")
        
        return ExecutionResult(
            success=True,
            message="Full workflow completed",
            data={
                "content": "\n\n".join(all_content),
                "steps": [(name, r.to_dict()) for name, r in results],
                "routing": routed.to_dict()
            }
        )
    
    def _execute_architecture(self, goal: str) -> ExecutionResult:
        """Execute architecture task."""
        result = self._execute_with_healing(
            "architect",
            goal,
            lambda: self._agents["architect"].process(goal)
        )
        if result.success:
            result.message = "Architecture design completed"
        return result
    
    def _execute_coding(self, goal: str) -> ExecutionResult:
        """Execute coding task."""
        result = self._execute_with_healing(
            "coder",
            goal,
            lambda: self._agents["coder"].process(goal)
        )
        if result.success:
            result.message = "Coding completed"
        return result
    
    def _execute_debug_fix(self, error: str) -> ExecutionResult:
        """Execute debugging and fixing."""
        result = self._execute_with_healing(
            "fixer",
            error,
            lambda: self._agents["fixer"].process(error)
        )
        if result.success:
            result.message = "Debug and fix completed"
        return result
    
    def _execute_debate(self, proposal: str) -> ExecutionResult:
        """Execute debate/critique."""
        result = self._execute_with_healing(
            "debator",
            proposal,
            lambda: self._agents["debator"].process(proposal)
        )
        if result.success:
            result.message = "Debate completed"
        return result
    
    def _execute_with_healing(self, agent_name: str,
                              task: str,
                              func: Callable[[], AgentResponse]) -> ExecutionResult:
        """
        Execute with self-healing on failure.
        
        Args:
            agent_name: Name of the agent
            task: The task being executed
            func: Function to execute
            
        Returns:
            ExecutionResult
        """
        self._emit("agent_start", f"{agent_name} started", agent=agent_name)
        result = func()
        
        if result.success:
            self._emit("agent_ok", f"{agent_name} completed", agent=agent_name)
            # Record success for learning
            self.self_improve.learn_from_task(
                task=task,
                agent_name=agent_name,
                prompt="",
                success=True,
                result=result.content
            )
            return ExecutionResult(
                success=True,
                message=f"{agent_name} completed",
                data=result.content,
                agent_name=agent_name
            )
        
        # Attempt healing
        if self.config.self_heal_enabled:
            self._emit("agent_fail", f"{agent_name} failed, attempting healing", agent=agent_name, error=result.error)
            healing_result = self._attempt_healing(agent_name, task, result)
            if healing_result:
                self._emit("heal_ok", f"Healing succeeded for {agent_name}", agent=agent_name)
                return healing_result
        
        self._emit("agent_fail", f"{agent_name} failed", agent=agent_name, error=result.error)
        return ExecutionResult(
            success=False,
            message=f"{agent_name} failed",
            data=result.content,
            error=result.error,
            agent_name=agent_name
        )
    
    def _attempt_healing(self, agent_name: str,
                        task: str,
                        failed_result: AgentResponse,
                        max_attempts: int = None) -> Optional[ExecutionResult]:
        """
        Attempt to heal/fix a failed execution.
        
        Args:
            agent_name: Which agent failed
            task: The original task
            failed_result: The failed result
            max_attempts: Maximum healing attempts
            
        Returns:
            ExecutionResult if healing succeeded, None otherwise
        """
        if max_attempts is None:
            max_attempts = self.config.max_heal_attempts
        
        current_result = failed_result
        reviewers = self._healing_reviewers_for(agent_name)
        if not reviewers:
            return None
        
        for attempt in range(max_attempts):
            self._emit("heal_try", f"Healing attempt {attempt + 1}/{max_attempts}", agent=agent_name)
            reviewer_name = reviewers[attempt % len(reviewers)]
            reviewer = self._agents[reviewer_name]
            fixer = self._agents["fixer"]

            failure_text = current_result.error or current_result.content
            review_task = (
                f"You are taking over recovery from the failed {agent_name} agent.\n"
                f"Original task:\n{task}\n\n"
                f"Failure details:\n{failure_text}\n\n"
                "Explain what likely broke and give a concrete repair plan for the fixer agent."
            )
            self._emit(
                "heal_handoff",
                f"Handoff to {reviewer_name} for recovery analysis",
                agent=reviewer_name,
                failed_agent=agent_name,
                attempt=attempt + 1,
            )
            review_response = self._call_agent_quick_process(
                reviewer,
                review_task,
                max_tokens=min(768, self._healing_max_tokens()),
                temperature=0.2,
            )
            if not review_response.success:
                self._emit(
                    "heal_review_fail",
                    f"{reviewer_name} could not prepare a recovery plan",
                    agent=reviewer_name,
                    failed_agent=agent_name,
                    error=review_response.error,
                )
                current_result = review_response
                continue

            review_guidance = review_response.content
            self._emit(
                "heal_review_ok",
                f"{reviewer_name} prepared a recovery plan",
                agent=reviewer_name,
                failed_agent=agent_name,
            )
            fix_task = (
                f"Original task: {task}\n"
                f"Failed agent: {agent_name}\n"
                f"Failure details: {failure_text}\n\n"
                f"Recovery guidance from {reviewer_name}:\n{review_guidance}"
            )
            self._emit(
                "heal_fix_start",
                f"Fixer applying {reviewer_name}'s recovery plan",
                agent="fixer",
                failed_agent=agent_name,
                reviewer=reviewer_name,
                attempt=attempt + 1,
            )
            fix_response = self._call_agent_quick_process(
                fixer,
                fix_task,
                max_tokens=self._healing_max_tokens(),
                temperature=0.2,
            )
            
            if fix_response.success:
                self._emit(
                    "heal_step",
                    f"Fixer succeeded with {reviewer_name}'s recovery plan",
                    agent="fixer",
                    failed_agent=agent_name,
                    reviewer=reviewer_name,
                )
                # Record successful healing
                self.self_improve.learn_from_task(
                    task=task,
                    agent_name="fixer",
                    prompt=fix_task,
                    success=True,
                    result=fix_response.content
                )
                
                return ExecutionResult(
                    success=True,
                    message=f"{agent_name} healed by fixer after {reviewer_name} handoff (attempt {attempt + 1})",
                    data=fix_response.content,
                    agent_name="fixer"
                )
            
            self._emit(
                "heal_step",
                f"Fixer failed after {reviewer_name} handoff",
                agent="fixer",
                failed_agent=agent_name,
                reviewer=reviewer_name,
                error=fix_response.error,
            )
            current_result = fix_response
        
        return None
    
    def _auto_git_commit(self, goal: str, result: ExecutionResult):
        """Automatically commit changes if git is enabled."""
        try:
            if not self.git_ops.is_repo():
                return
            
            # Get status to see what changed
            status = self.git_ops.status()
            
            if status.get("clean"):
                return
            
            # Stage all changes
            self.git_ops.add()
            
            # Commit with descriptive message
            message = f"{self.config.git.commit_message_prefix} {goal[:50]}"
            
            commit_result = self.git_ops.commit(message)
            
            if commit_result.get("success"):
                self.memory_store.add(
                    content=f"Auto-committed: {message}\nHash: {commit_result.get('commit_hash', 'N/A')}",
                    entry_type="git",
                    tags=["git", "commit"],
                    importance=3
                )
        except Exception:
            # Don't fail the workflow for git issues
            pass
    
    def add_task(self, description: str, priority: TaskPriority = TaskPriority.NORMAL,
                 dependencies: Optional[List[str]] = None) -> Task:
        """Add a task to the queue."""
        return self.task_queue.add(
            description=description,
            priority=priority,
            dependencies=dependencies
        )
    
    def run_queue(self, max_iterations: int = 100) -> Dict[str, Any]:
        """
        Run tasks from the queue.
        
        Args:
            max_iterations: Maximum number of tasks to process
            
        Returns:
            Summary of run
        """
        results = {
            "completed": 0,
            "failed": 0,
            "iterations": 0
        }
        
        for i in range(max_iterations):
            task = self.task_queue.get_next_task()
            
            if not task:
                break
            
            self._current_task = task
            self.task_queue.mark_started(task.id)
            
            try:
                exec_result = self.execute_goal(task.description)
                
                if exec_result.success:
                    self.task_queue.mark_completed(task.id, exec_result.message)
                    results["completed"] += 1
                else:
                    self.task_queue.mark_failed(task.id, exec_result.error or "Unknown error")
                    results["failed"] += 1
                    
                    # Try to retry
                    if task.can_retry():
                        self.task_queue.retry_task(task.id)
                
            except Exception as e:
                self.task_queue.mark_failed(task.id, str(e))
                results["failed"] += 1
            
            results["iterations"] += 1
            self._current_task = None
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the orchestrator."""
        return {
            "session_id": self.session_id,
            "running": self.running,
            "current_task": self._current_task.description if self._current_task else None,
            "queue_stats": self.task_queue.get_stats(),
            "git_status": self.git_ops.status() if self.git_ops.is_repo() else None,
            "memory_stats": self.memory_store.get_stats(),
            "ollama": self._get_ollama_health(),
            "warmup": self._warmup_status,
            "config": {
                "workspace_root": self.config.workspace_root,
                "self_heal_enabled": self.config.self_heal_enabled,
                "git_auto_commit": self.config.git.auto_commit,
                "ollama_host": self.config.ollama_host,
                "models": self.config.models,
                "ollama_primary_model": getattr(self.config, "ollama_primary_model", None),
                "ollama_fallback_models": getattr(self.config, "ollama_fallback_models", None),
                "ollama_max_context_tokens": getattr(self.config, "ollama_max_context_tokens", None),
                "ollama_temperature": getattr(self.config, "ollama_temperature", None),
                "ollama_timeout_seconds": getattr(self.config, "ollama_timeout_seconds", None),
            }
        }

    def _get_ollama_health(self, cache_seconds: int = 10) -> Dict[str, Any]:
        """Best-effort model-runtime health check (cached)."""
        now = time.time()
        if self._ollama_health_cache and (now - self._ollama_health_cache_ts) < cache_seconds:
            return self._ollama_health_cache

        try:
            client = next(iter(self._agents.values())).ollama if self._agents else None
            if client is None:
                payload = {
                    "ok": False,
                    "host": self.config.ollama_host,
                    "models": [],
                    "local_ok": False,
                    "local_error": "No agents available for runtime probe",
                    "remote_ready": False,
                    "error": "No agents available for runtime probe",
                }
            else:
                health = client.health()
                payload = {
                    "ok": bool(health.get("ok")),
                    "host": health.get("host", self.config.ollama_host),
                    "models": list(health.get("models") or []),
                    "local_ok": bool(health.get("local_ok")),
                    "local_error": health.get("local_error"),
                    "remote_ready": bool(health.get("remote_ready")),
                }
                if health.get("local_error"):
                    payload["error"] = health["local_error"]
        except Exception as e:
            payload = {
                "ok": False,
                "host": self.config.ollama_host,
                "models": [],
                "local_ok": False,
                "local_error": str(e),
                "remote_ready": False,
                "error": str(e),
            }

        self._ollama_health_cache = payload
        self._ollama_health_cache_ts = now
        return payload
    
    def shell(self, command: str) -> Dict[str, Any]:
        """Execute a shell command."""
        return self.shell_tool.run_shell(command)
    
    def python(self, code: str) -> Dict[str, Any]:
        """Execute Python code."""
        return self.shell_tool.run_python(code)
    
    def read_file(self, path: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Read a file."""
        return self.file_ops.read_file(path, limit=limit)
    
    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Write a file."""
        return self.file_ops.write_file(path, content)
    
    def git(self, *args) -> Dict[str, Any]:
        """Execute a git command."""
        return self.git_ops._run_git(*args)
