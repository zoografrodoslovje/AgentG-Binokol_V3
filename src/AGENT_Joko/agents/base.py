"""
Base agent class for the Devin Agent system.
Provides common functionality for all agents.
"""

import time
import json
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from ..config import Config, AgentConfig
from ..memory import ContextManager, JsonStore
from ..tools import FileOps, ShellTool, GitOps
from ..ollama_client import OllamaClient, OllamaError


@dataclass
class AgentResponse:
    """Response from an agent operation."""
    success: bool
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float = 0.0


class BaseAgent(ABC):
    """Base class for all agents."""
    
    def __init__(self, name: str, config: Config, session_id: str = "default"):
        """
        Initialize the base agent.
        
        Args:
            name: Agent name (architect, coder, tester, fixer, debator)
            config: System configuration
            session_id: Session identifier
        """
        self.name = name
        self.config = config
        self.session_id = session_id
        
        # Get agent-specific config
        self.agent_config = config.agent_configs.get(name, AgentConfig(
            model=config.get_model_for_agent(name),
            system_prompt=f"You are a {name} agent."
        ))
        
        # Initialize components
        storage_path = config.memory.storage_path
        self.memory_store = JsonStore(
            storage_path=storage_path,
            max_entries=config.memory.max_entries
        )
        self.context_manager = ContextManager(
            memory_store=self.memory_store,
            context_window=config.memory.context_window
        )
        self.file_ops = FileOps(workspace_root=config.workspace_root)
        self.shell_tool = ShellTool(workspace_root=config.workspace_root)
        self.git_ops = GitOps(repo_path=config.workspace_root)
        
        # Response history
        self.response_history: List[AgentResponse] = []
        
        # Ollama API
        self.ollama_host = config.ollama_host
        self.ollama = OllamaClient(
            host=config.ollama_host,
            timeout_seconds=getattr(config, "ollama_timeout_seconds", self.agent_config.timeout_seconds),
            max_context_tokens=getattr(config, "ollama_max_context_tokens", 2048),
            temperature=getattr(config, "ollama_temperature", self.agent_config.temperature),
            idle_keep_alive_minutes=getattr(config, "ollama_idle_timeout_minutes", 5),
            enable_caching=getattr(config, "ollama_enable_caching", True),
            cache_ttl_seconds=getattr(config, "ollama_cache_ttl_seconds", 300),
            cache_max_entries=getattr(config, "ollama_cache_max_entries", 200),
            groq_api_key=getattr(config, "groq_api_key", None),
            groq_base_url=getattr(config, "groq_base_url", "https://api.groq.com/openai/v1"),
            openai_api_key=getattr(config, "openai_api_key", None),
            openai_base_url=getattr(config, "openai_base_url", "https://api.openai.com/v1"),
            openrouter_api_key=getattr(config, "openrouter_api_key", None),
            openrouter_base_url=getattr(config, "openrouter_base_url", "https://openrouter.ai/api/v1"),
            catalog_models=self._catalog_models(config),
        )

    @staticmethod
    def _catalog_models(config: Config) -> List[str]:
        catalog = getattr(config, "provider_catalog_models", {}) or {}
        ordered: List[str] = []
        seen = set()
        for provider_models in catalog.values():
            for model_name in provider_models or []:
                if not model_name or model_name in seen:
                    continue
                seen.add(model_name)
                ordered.append(model_name)
        return ordered
    
    @abstractmethod
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process a task. Must be implemented by subclasses.
        
        Args:
            task: The task to process
            context: Optional additional context
            
        Returns:
            AgentResponse with results
        """
        pass
    
    def _call_ollama(self, model: Optional[str] = None,
                     messages: Optional[List[Dict]] = None,
                     system_prompt: Optional[str] = None,
                     prompt: Optional[str] = None,
                     temperature: Optional[float] = None,
                     max_tokens: Optional[int] = None,
                     stop: Optional[List[str]] = None,
                     fallback_models: Optional[List[str]] = None,
                     timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        """
        Call Ollama API.
        
        Args:
            model: Model name (defaults to agent's model)
            messages: Chat-style messages
            system_prompt: System prompt
            prompt: Direct prompt (for completion-style)
            temperature: Temperature setting
            max_tokens: Max tokens to generate
            stop: Stop sequences
            
        Returns:
            Response dictionary
        """
        selected_model = model or self.agent_config.model
        temp = temperature if temperature is not None else self.agent_config.temperature
        token_limit = max_tokens if max_tokens is not None else self.agent_config.max_tokens

        options: Dict[str, Any] = {
            "temperature": float(temp),
            "num_predict": int(token_limit),
        }
        per_agent_ctx = getattr(self.agent_config, "num_ctx", None)
        if per_agent_ctx:
            options["num_ctx"] = int(per_agent_ctx)
        if stop:
            options["stop"] = stop

        fallback_models = list(fallback_models if fallback_models is not None else (
            getattr(self.config, "ollama_fallback_models", []) or []
        ))
        fallback_models = self._sanitize_fallback_models(selected_model, fallback_models)

        try:
            if prompt is not None:
                res = self.ollama.generate(
                    prompt=prompt,
                    model=selected_model,
                    fallback_models=fallback_models,
                    options=options,
                    system=system_prompt,
                    timeout_seconds=timeout_seconds,
                )
                content = res.get("content", "")
            elif messages is not None:
                res = self.ollama.chat(
                    messages=messages,  # type: ignore[arg-type]
                    model=selected_model,
                    fallback_models=fallback_models,
                    options=options,
                    system=system_prompt,
                    timeout_seconds=timeout_seconds,
                )
                content = res.get("content", "")
            else:
                return {"success": False, "error": "Either prompt or messages required"}

            return {
                "success": True,
                "response": content,
                "model": res.get("model", selected_model),
                "usage": res.get("usage", {}),
                "raw": res.get("raw", {}),
                "done": True,
            }
        except OllamaError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _sanitize_fallback_models(self, primary_model: str, fallback_models: List[str]) -> List[str]:
        """Deduplicate fallback models and skip known slow fallback loops."""
        cleaned: List[str] = []
        seen = {primary_model}
        for model_name in fallback_models:
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            if "qwen" in model_name.lower():
                continue
            cleaned.append(model_name)
        return cleaned

    def quick_process(
        self,
        task: str,
        context: Optional[str] = None,
        *,
        max_tokens: int = 1024,
        timeout_seconds: Optional[int] = None,
        fallback_models: Optional[List[str]] = None,
        temperature: Optional[float] = None,
    ) -> AgentResponse:
        """Run a smaller/faster agent pass for recovery and fallback flows."""
        try:
            messages = self._format_messages(task, context)
            result = self._call_ollama(
                model=self.config.get_model_for_agent(self.name),
                messages=messages,
                temperature=temperature if temperature is not None else self.agent_config.temperature,
                max_tokens=max_tokens,
                fallback_models=fallback_models,
                timeout_seconds=timeout_seconds,
            )
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to call Ollama"))

            response_text = result["response"]
            self.add_to_context("assistant", response_text)
            return self._wrap_response(
                content=response_text,
                metadata={"task": task[:80], "agent": self.name, "mode": "quick"}
            )
        except Exception as e:
            return self._wrap_error(f"{self.name} quick_process error: {str(e)}")
    
    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse tool calls from response text.
        
        Looks for patterns like:
        [TOOL_CALL] write_file:path/to/file:content [/TOOL_CALL]
        """
        import re
        
        tool_calls = []
        
        # Pattern for tool calls
        pattern = r'\[TOOL_CALL\]\s*(\w+):([^:]+):(.+?)\s*\[\/TOOL_CALL\]'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for tool_name, path, content in matches:
            tool_calls.append({
                "tool": tool_name,
                "path": path.strip(),
                "content": content.strip()
            })
        
        return tool_calls
    
    def _execute_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a parsed tool call.
        
        Args:
            tool_call: Tool call dictionary
            
        Returns:
            Execution result
        """
        tool_name = tool_call.get("tool")
        path = tool_call.get("path", "")
        content = tool_call.get("content", "")
        
        if tool_name == "write_file":
            return self.file_ops.write_file(path, content)
        elif tool_name == "read_file":
            return self.file_ops.read_file(path)
        elif tool_name == "list_files":
            return self.file_ops.list_files(path)
        elif tool_name == "run_shell":
            return self.shell_tool.run_shell(content)
        elif tool_name == "run_python":
            return self.shell_tool.run_python(content)
        else:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for this agent."""
        parts = [self.agent_config.system_prompt]
        
        # Add workspace info
        parts.append(f"\n\nWorkspace: {self.config.workspace_root}")
        
        # Add available tools info
        parts.append("\n\nAvailable tools:")
        parts.append("- write_file(path, content)")
        parts.append("- read_file(path)")
        parts.append("- list_files(path='.', pattern=None)")
        parts.append("- run_shell(command)")
        parts.append("- run_python(code)")
        parts.append("- git_commit(message)")
        
        return "\n".join(parts)
    
    def _format_messages(self, task: str, context: Optional[str] = None) -> List[Dict]:
        """
        Format messages for LLM.
        
        Args:
            task: The task to include
            context: Optional additional context
            
        Returns:
            List of message dictionaries
        """
        messages = []
        
        # System prompt
        messages.append({
            "role": "system",
            "content": self._build_system_prompt()
        })
        
        # Add context from context manager
        stored_context = self.context_manager.build_system_prompt(
            self.name, self.session_id, context
        )
        
        if stored_context:
            messages.append({
                "role": "system",
                "content": f"\n\nRelevant context:\n{stored_context}"
            })
        
        # User task
        task_content = task
        if context:
            task_content = f"{task}\n\nContext: {context}"
        
        messages.append({
            "role": "user",
            "content": task_content
        })
        
        return messages
    
    def add_to_context(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the agent's context history."""
        self.context_manager.add_to_context(
            self.name, self.session_id, role, content, metadata
        )
    
    def save_to_memory(self, content: str, entry_type: str = "context",
                       tags: Optional[List[str]] = None,
                       metadata: Optional[Dict] = None,
                       importance: int = 3):
        """Save content to persistent memory."""
        self.memory_store.add(
            content=content,
            entry_type=entry_type,
            tags=tags,
            metadata=metadata,
            importance=importance
        )
    
    def get_recent_context(self, count: int = 10) -> str:
        """Get recent context as a string."""
        entries = self.memory_store.get_recent(count=count)
        if not entries:
            return ""
        
        parts = []
        for entry in entries:
            parts.append(f"[{entry.type}] {entry.content[:200]}")
        
        return "\n".join(parts)
    
    def _wrap_response(self, content: str, tool_calls: List[Dict] = None,
                      metadata: Dict = None) -> AgentResponse:
        """Create an AgentResponse wrapper."""
        return AgentResponse(
            success=True,
            content=content,
            tool_calls=tool_calls or [],
            metadata=metadata or {}
        )
    
    def _wrap_error(self, error: str) -> AgentResponse:
        """Create an error AgentResponse."""
        return AgentResponse(
            success=False,
            content="",
            error=error
        )
