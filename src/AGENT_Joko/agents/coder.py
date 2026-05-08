"""
Coder agent for the Devin Agent system.
Writes and implements code.
"""

from typing import Dict, Any, Optional
from .base import BaseAgent, AgentResponse


class CoderAgent(BaseAgent):
    """
    Coder agent that writes and implements code.
    
    Responsibilities:
    - Write clean, efficient, well-documented code
    - Implement features following architectural plans
    - Create modular and reusable code
    - Follow language-specific best practices
    """
    
    def __init__(self, config, session_id: str = "default"):
        """Initialize the coder agent."""
        super().__init__("coder", config, session_id)
    
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process a coding task.
        
        Args:
            task: The coding task to implement
            context: Optional context (e.g., from architect)
            
        Returns:
            AgentResponse with implementation results
        """
        try:
            # Build prompt with context about writing good code
            coding_task = f"""Implement the following task. Produce the actual deliverable requested by the user, not just a description of it.

{task}

Requirements:
- Follow best practices for the language being used
- Include proper error handling
- Add docstrings/comments where appropriate
- Make the code modular and reusable
- Handle edge cases
- If the task asks for a single file such as a Python script, JSON file, text file, HTML page, or Markdown file, return the final file contents directly in a single fenced code block with the correct language
- Prefer creating the exact requested file type instead of giving a plan or prose explanation
- Use the write_file tool call when you can determine the intended file path confidently
- For Python tasks, the runtime already includes `requests`, `urllib3`, `beautifulsoup4`, `lxml`, `httpx`, and `pandas`; use them when appropriate instead of re-implementing basic HTTP, HTML parsing, or tabular data handling

Return your implementation. If you need to create multiple files, use the write_file tool call.
If explaining changes, be clear and concise."""

            messages = self._format_messages(coding_task, context)
            
            # Call Ollama
            result = self._call_ollama(
                model=self.config.get_model_for_agent("coder"),
                messages=messages,
                temperature=self.agent_config.temperature,
                max_tokens=self.agent_config.max_tokens,
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to call Ollama"))
            
            response_text = result["response"]
            
            # Parse tool calls
            tool_calls = self._parse_tool_calls(response_text)
            
            # Execute any tool calls
            executed_results = []
            for tool_call in tool_calls:
                exec_result = self._execute_tool_call(tool_call)
                executed_results.append({
                    "tool": tool_call.get("tool"),
                    "path": tool_call.get("path"),
                    "result": exec_result
                })
            
            # Store in context
            self.add_to_context("assistant", response_text)
            
            # Save to memory
            self.save_to_memory(
                content=f"Implementation: {task[:100]}\n\nExecuted {len(tool_calls)} file operations",
                entry_type="implementation",
                tags=["code", "implementation"],
                importance=4
            )
            
            return self._wrap_response(
                content=response_text,
                tool_calls=executed_results,
                metadata={"task": task[:50], "files_created": len(tool_calls)}
            )
            
        except Exception as e:
            return self._wrap_error(f"Coder agent error: {str(e)}")
    
    def write_file(self, path: str, content: str, execute: bool = True) -> AgentResponse:
        """
        Write a file with the given content.
        
        Args:
            path: File path
            content: File content
            execute: Whether to actually write the file
            
        Returns:
            AgentResponse with result
        """
        try:
            if execute:
                result = self.file_ops.write_file(path, content)
                
                if result["success"]:
                    self.save_to_memory(
                        content=f"Created file: {path}",
                        entry_type="file_creation",
                        tags=["file", path],
                        importance=3
                    )
                    return self._wrap_response(
                        content=f"File created: {path}",
                        metadata={"path": path, "bytes": result.get("bytes", 0)}
                    )
                else:
                    return self._wrap_error(result.get("error", "Failed to write file"))
            else:
                return self._wrap_response(
                    content=f"Would create file: {path}",
                    metadata={"path": path, "dry_run": True}
                )
        except Exception as e:
            return self._wrap_error(f"Write file error: {str(e)}")
    
    def implement_feature(self, feature: str, existing_code: Optional[str] = None,
                          language: str = "python") -> AgentResponse:
        """
        Implement a specific feature.
        
        Args:
            feature: Feature description
            existing_code: Existing code to build upon
            language: Programming language
            
        Returns:
            AgentResponse with implementation
        """
        context_parts = [f"Language: {language}"]
        
        if existing_code:
            context_parts.append(f"\nExisting code:\n{existing_code[:2000]}")
        
        prompt = f"""Implement this feature in {language}:

{feature}

Write complete, production-ready code. Include:
- Proper imports
- Error handling
- Documentation
- Type hints (for Python) or JSDoc (for JS/TS)"""

        messages = self._format_messages(prompt, "\n".join(context_parts))
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("coder"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            # Parse and execute tool calls
            tool_calls = self._parse_tool_calls(result["response"])
            for tool_call in tool_calls:
                self._execute_tool_call(tool_call)
            
            return self._wrap_response(
                content=result["response"],
                tool_calls=tool_calls
            )
        return self._wrap_error(result.get("error", "Failed to implement feature"))
    
    def refactor_code(self, code: str, goal: str = "improve readability and maintainability") -> AgentResponse:
        """
        Refactor existing code.
        
        Args:
            code: Code to refactor
            goal: Refactoring goal
            
        Returns:
            AgentResponse with refactored code
        """
        prompt = f"""Refactor this code with the goal: {goal}

Original code:
{code}

Provide the refactored version with an explanation of changes made."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("coder"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "refactoring", "goal": goal}
            )
        return self._wrap_error(result.get("error", "Failed to refactor"))
