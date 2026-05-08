"""
Architect agent for the Devin Agent system.
Plans architecture and breaks down complex tasks.
"""

from typing import Dict, Any, Optional, List
from .base import BaseAgent, AgentResponse


class ArchitectAgent(BaseAgent):
    """
    Architect agent that designs system architecture and implementation plans.
    
    Responsibilities:
    - Analyze requirements and design system architecture
    - Break down complex tasks into manageable components
    - Create detailed implementation plans
    - Anticipate technical challenges
    """
    
    def __init__(self, config, session_id: str = "default"):
        """Initialize the architect agent."""
        super().__init__("architect", config, session_id)
    
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process an architecture task.
        
        Args:
            task: The task/requirement to architect
            context: Optional context
            
        Returns:
            AgentResponse with architecture plan
        """
        try:
            # Build messages for LLM
            messages = self._format_messages(
                f"""Analyze the following task and create a detailed architecture plan:

{task}

Provide a structured response with:
1. System Overview - High-level description
2. Component Breakdown - List of main components/modules
3. Implementation Plan - Step-by-step implementation order
4. Technical Considerations - Key technical decisions and challenges
5. File Structure - Suggested file organization

Be specific and detailed. Consider clean architecture, separation of concerns, and scalability.""",
                context
            )
            
            # Call Ollama
            result = self._call_ollama(
                model=self.config.get_model_for_agent("architect"),
                messages=messages,
                temperature=self.agent_config.temperature,
                max_tokens=self.agent_config.max_tokens,
            )
            
            if not result["success"]:
                return self._wrap_error(result.get("error", "Failed to call Ollama"))
            
            response_text = result["response"]
            
            # Parse any tool calls
            tool_calls = self._parse_tool_calls(response_text)
            
            # Store in context
            self.add_to_context("assistant", response_text)
            
            # Save to memory for future reference
            self.save_to_memory(
                content=f"Architecture plan for: {task[:100]}\n\n{response_text}",
                entry_type="architecture",
                tags=["architecture", "plan"],
                importance=4
            )
            
            return self._wrap_response(
                content=response_text,
                tool_calls=tool_calls,
                metadata={"task": task, "agent": "architect"}
            )
            
        except Exception as e:
            return self._wrap_error(f"Architect agent error: {str(e)}")
    
    def design_file_structure(self, task: str) -> Dict[str, Any]:
        """
        Design a file structure for a task.
        
        Args:
            task: The task description
            
        Returns:
            Dictionary with file structure suggestions
        """
        prompt = f"""Based on this task, suggest an optimal file/folder structure:

{task}

Respond in JSON format:
{{
  "root": "project_name",
  "structure": [
    {{"path": "src/main.py", "description": "..."}},
    {{"path": "src/utils/helpers.py", "description": "..."}}
  ],
  "reasoning": "..."
}}"""
        
        messages = [
            {"role": "system", "content": "You are an architecture expert. Provide clean, scalable file structures."},
            {"role": "user", "content": prompt}
        ]
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("architect"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            return {"success": True, "structure": result["response"]}
        return {"success": False, "error": result.get("error")}
    
    def review_architecture(self, current_code: str, requirements: str) -> AgentResponse:
        """
        Review an existing architecture against requirements.
        
        Args:
            current_code: Current code or architecture description
            requirements: Requirements to check against
            
        Returns:
            AgentResponse with review findings
        """
        prompt = f"""Review this architecture/code against the requirements:

CURRENT ARCHITECTURE/CODE:
{current_code}

REQUIREMENTS:
{requirements}

Provide a review covering:
1. Alignment with requirements
2. Architectural issues or improvements needed
3. Technical debt or concerns
4. Recommendations for improvement

Be critical but constructive."""
        
        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("architect"),
            messages=messages
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"review": "architecture"}
            )
        return self._wrap_error(result.get("error", "Failed to review"))
