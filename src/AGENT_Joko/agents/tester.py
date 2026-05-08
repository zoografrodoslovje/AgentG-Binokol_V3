"""
Tester agent for the Devin Agent system.
Tests and validates code.
"""

from typing import Dict, Any, Optional, List
from .base import BaseAgent, AgentResponse


class TesterAgent(BaseAgent):
    """
    Tester agent that tests and validates code.
    
    Responsibilities:
    - Design and write comprehensive test cases
    - Validate functionality against specifications
    - Identify edge cases and potential failures
    - Ensure code quality and reliability
    """
    
    def __init__(self, config, session_id: str = "default"):
        """Initialize the tester agent."""
        super().__init__("tester", config, session_id)
    
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process a testing task.
        
        Args:
            task: The testing task
            context: Optional context with code to test
            
        Returns:
            AgentResponse with test results
        """
        try:
            prompt = f"""Design and execute tests for this task:

{task}

Provide:
1. Test cases covering:
   - Happy path scenarios
   - Edge cases
   - Error conditions
2. Execute the tests if possible
3. Report results with pass/fail status

Be thorough and specific about what you're testing and what the expected outcomes are."""

            messages = self._format_messages(prompt, context)
            
            result = self._call_ollama(
                model=self.config.get_model_for_agent("tester"),
                messages=messages,
                temperature=self.agent_config.temperature,
                max_tokens=self.agent_config.max_tokens,
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to call Ollama"))
            
            response_text = result["response"]
            self.add_to_context("assistant", response_text)
            
            return self._wrap_response(
                content=response_text,
                metadata={"task": task[:50], "agent": "tester"}
            )
            
        except Exception as e:
            return self._wrap_error(f"Tester agent error: {str(e)}")
    
    def generate_tests(self, code: str, language: str = "python",
                       framework: Optional[str] = None) -> AgentResponse:
        """
        Generate test cases for code.
        
        Args:
            code: Code to generate tests for
            language: Programming language
            framework: Testing framework (pytest, unittest, jest, etc.)
            
        Returns:
            AgentResponse with generated tests
        """
        if framework is None:
            framework = "pytest" if language == "python" else "jest"
        
        prompt = f"""Generate comprehensive test cases for this {language} code using {framework}:

{code}

Requirements:
- Test all public functions/methods
- Include edge case tests
- Add docstrings to test functions
- Use appropriate assertions
- Follow {framework} best practices

Return the test file content using write_file tool calls."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("tester"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            tool_calls = self._parse_tool_calls(result["response"])
            
            # Execute write operations
            test_files = []
            for tool_call in tool_calls:
                if tool_call.get("tool") == "write_file":
                    exec_result = self._execute_tool_call(tool_call)
                    if exec_result.get("success"):
                        test_files.append(tool_call.get("path"))
            
            return self._wrap_response(
                content=result["response"],
                tool_calls=tool_calls,
                metadata={"test_files": test_files, "framework": framework}
            )
        return self._wrap_error(result.get("error", "Failed to generate tests"))
    
    def run_tests(self, test_file: str, verbose: bool = True) -> AgentResponse:
        """
        Run tests in a test file.
        
        Args:
            test_file: Path to test file
            verbose: Whether to show verbose output
            
        Returns:
            AgentResponse with test results
        """
        try:
            # Determine how to run based on file extension
            if test_file.endswith(".py"):
                cmd = f"{self.shell_tool.python_path} -m pytest {test_file}"
                if verbose:
                    cmd += " -v"
            elif test_file.endswith(".js") or test_file.endswith(".ts"):
                cmd = f"npm test -- {test_file}"
            else:
                return self._wrap_error(f"Unknown test file type: {test_file}")
            
            result = self.shell_tool.run_shell(cmd, timeout=120)
            
            return AgentResponse(
                success=result.get("success", False),
                content=result.get("stdout", "") + "\n" + result.get("stderr", ""),
                metadata={"test_file": test_file, "returncode": result.get("returncode")}
            )
            
        except Exception as e:
            return self._wrap_error(f"Run tests error: {str(e)}")
    
    def validate_output(self, expected: str, actual: str, description: str = "") -> AgentResponse:
        """
        Validate actual output against expected.
        
        Args:
            expected: Expected output
            actual: Actual output
            description: Test description
            
        Returns:
            AgentResponse with validation result
        """
        prompt = f"""Compare these outputs and validate:

Test: {description}

Expected output:
{expected}

Actual output:
{actual}

Determine if they match (consider whitespace variations and minor differences).
Report pass/fail with reasoning."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("tester"),
            messages=messages,
            temperature=0.1  # Low temperature for precise comparison
        )
        
        if result["success"]:
            response = result["response"].lower()
            passed = "pass" in response and "fail" not in response.split("pass")[0]
            
            return self._wrap_response(
                content=result["response"],
                metadata={
                    "validated": passed,
                    "description": description
                }
            )
        return self._wrap_error(result.get("error", "Failed to validate"))
    
    def test_edge_cases(self, function_code: str, language: str = "python") -> AgentResponse:
        """
        Identify and test edge cases for a function.
        
        Args:
            function_code: The function to test
            language: Programming language
            
        Returns:
            AgentResponse with edge case tests
        """
        prompt = f"""Identify and test edge cases for this {language} function:

{function_code}

Consider:
- Empty inputs
- None/null values
- Boundary values (0, max int, empty string, etc.)
- Invalid inputs
- Very large inputs
- Special characters

Write test cases that cover these scenarios."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("tester"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "edge_case_testing"}
            )
        return self._wrap_error(result.get("error", "Failed to test edge cases"))
