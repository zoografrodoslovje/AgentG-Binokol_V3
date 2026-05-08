"""
Fixer agent for the Devin Agent system.
Fixes issues and debugs code.
"""

from typing import Dict, Any, Optional
from .base import BaseAgent, AgentResponse


class FixerAgent(BaseAgent):
    """
    Fixer agent that fixes issues and debugs code.
    
    Responsibilities:
    - Debug and fix issues in code
    - Analyze error messages and stack traces
    - Implement targeted fixes
    - Validate that fixes resolve the issues
    """
    
    def __init__(self, config, session_id: str = "default"):
        """Initialize the fixer agent."""
        super().__init__("fixer", config, session_id)
    
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process a debugging/fixing task.
        
        Args:
            task: The issue to fix
            context: Optional context with error details
            
        Returns:
            AgentResponse with fix results
        """
        try:
            prompt = f"""Debug and fix the following issue:

{task}

Process:
1. Analyze the error/issue carefully
2. Identify the root cause
3. Implement a minimal, targeted fix
4. Verify the fix works

Focus on accuracy - fix only what's broken without introducing new issues."""

            messages = self._format_messages(prompt, context)
            
            result = self._call_ollama(
                model=self.config.get_model_for_agent("fixer"),
                messages=messages,
                temperature=self.agent_config.temperature,
                max_tokens=self.agent_config.max_tokens,
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to call Ollama"))
            
            response_text = result["response"]
            
            # Parse and execute tool calls
            tool_calls = self._parse_tool_calls(response_text)
            for tool_call in tool_calls:
                self._execute_tool_call(tool_call)
            
            self.add_to_context("assistant", response_text)
            
            return self._wrap_response(
                content=response_text,
                tool_calls=tool_calls,
                metadata={"task": task[:50], "agent": "fixer"}
            )
            
        except Exception as e:
            return self._wrap_error(f"Fixer agent error: {str(e)}")
    
    def analyze_error(self, error: str, code: Optional[str] = None) -> AgentResponse:
        """
        Analyze an error message.
        
        Args:
            error: Error message or traceback
            code: Optional code context
            
        Returns:
            AgentResponse with analysis
        """
        context_parts = [f"Error to analyze:\n{error}"]
        if code:
            context_parts.append(f"\nCode context:\n{code[:1500]}")
        
        prompt = """Analyze this error message carefully:

"""

        messages = self._format_messages(prompt, "\n".join(context_parts))
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("fixer"),
            messages=messages,
            temperature=0.1
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "error_analysis"}
            )
        return self._wrap_error(result.get("error", "Failed to analyze error"))
    
    def fix_and_validate(self, code: str, error: str, test_command: Optional[str] = None) -> AgentResponse:
        """
        Fix code and validate the fix.
        
        Args:
            code: Code with the error
            error: The error message
            test_command: Optional command to run to validate
            
        Returns:
            AgentResponse with fix and validation results
        """
        try:
            # Get the fix
            prompt = f"""Fix this code that has an error:

Error: {error}

Code:
{code}

Provide:
1. Analysis of the root cause
2. The fixed code
3. Brief explanation of the change

Use write_file tool call if you need to modify files."""

            messages = self._format_messages(prompt)
            
            result = self._call_ollama(
                model=self.config.get_model_for_agent("fixer"),
                messages=messages,
                temperature=0.2
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to fix"))
            
            response_text = result["response"]
            tool_calls = self._parse_tool_calls(response_text)
            
            # Execute tool calls
            fix_applied = False
            for tool_call in tool_calls:
                if tool_call.get("tool") == "write_file":
                    exec_result = self._execute_tool_call(tool_call)
                    if exec_result.get("success"):
                        fix_applied = True
            
            # Run validation if command provided
            validation_result = None
            if test_command and fix_applied:
                validation_result = self.shell_tool.run_shell(test_command)
            
            self.add_to_context("assistant", response_text)
            
            self.save_to_memory(
                content=f"Fix applied: {error[:100]}\n\nFix: {response_text[:500]}",
                entry_type="fix",
                tags=["bug", "fix"],
                importance=4
            )
            
            return self._wrap_response(
                content=response_text,
                tool_calls=tool_calls,
                metadata={
                    "error": error,
                    "fix_applied": fix_applied,
                    "validation": validation_result
                }
            )
            
        except Exception as e:
            return self._wrap_error(f"Fix and validate error: {str(e)}")
    
    def fix_file(self, path: str, issue: str) -> AgentResponse:
        """
        Fix issues in a specific file.
        
        Args:
            path: File path
            issue: Description of the issue
            
        Returns:
            AgentResponse with fix results
        """
        try:
            # Read the file
            read_result = self.file_ops.read_file(path)
            if not read_result.get("success"):
                return self._wrap_error(f"Could not read file: {path}")
            
            code = read_result.get("content", "")
            
            # Generate fix
            prompt = f"""Fix this file. Issue: {issue}

File: {path}
Content:
{code}

Provide the fixed version and explain the changes."""

            messages = self._format_messages(prompt)
            
            result = self._call_ollama(
                model=self.config.get_model_for_agent("fixer"),
                messages=messages,
                temperature=0.2
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error"))
            
            response_text = result["response"]
            
            # Check if there's a fixed version to write
            tool_calls = self._parse_tool_calls(response_text)
            
            for tool_call in tool_calls:
                if tool_call.get("tool") == "write_file":
                    exec_result = self._execute_tool_call(tool_call)
                    if exec_result.get("success"):
                        return self._wrap_response(
                            content=f"Fixed {path}: {response_text}",
                            metadata={"path": path, "fixed": True}
                        )
            
            # If no write_file call, try to extract and write the fixed code
            # Look for code blocks
            import re
            code_block_pattern = r'```[\w]*\n(.+?)```'
            matches = re.findall(code_block_pattern, response_text, re.DOTALL)
            
            if matches:
                # Write the last code block (likely the fixed version)
                fixed_code = matches[-1]
                write_result = self.file_ops.write_file(path, fixed_code)
                
                if write_result.get("success"):
                    return self._wrap_response(
                        content=f"Fixed {path}",
                        metadata={"path": path, "fixed": True}
                    )
            
            return self._wrap_response(
                content=response_text,
                metadata={"path": path, "needs_manual_fix": True}
            )
            
        except Exception as e:
            return self._wrap_error(f"Fix file error: {str(e)}")
    
    def suggest_fixes(self, error: str, code: str) -> AgentResponse:
        """
        Suggest multiple possible fixes for an error.
        
        Args:
            error: Error message
            code: Code with the error
            
        Returns:
            AgentResponse with fix suggestions
        """
        prompt = f"""Suggest possible fixes for this error:

Error: {error}

Code:
{code}

For each potential fix:
1. Describe the approach
2. Show the relevant code change
3. Explain the tradeoffs
4. Rate confidence (high/medium/low)

List multiple options if applicable."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("fixer"),
            messages=messages,
            temperature=0.4  # Higher for variety of suggestions
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "fix_suggestions", "error": error}
            )
        return self._wrap_error(result.get("error", "Failed to suggest fixes"))
