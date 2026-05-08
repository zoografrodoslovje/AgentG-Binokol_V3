"""
Debator agent for the Devin Agent system.
Critiques and debates plans for better solutions.
"""

from typing import Dict, Any, Optional, List
from .base import BaseAgent, AgentResponse


class DebatorAgent(BaseAgent):
    """
    Debator agent that critiques and debates plans for better solutions.
    
    Responsibilities:
    - Critically analyze plans and proposals
    - Identify weaknesses and potential problems
    - Suggest alternative approaches
    - Challenge assumptions and improve solutions
    """
    
    def __init__(self, config, session_id: str = "default"):
        """Initialize the debator agent."""
        super().__init__("debator", config, session_id)
    
    def process(self, task: str, context: Optional[str] = None) -> AgentResponse:
        """
        Process a critique/debate task.
        
        Args:
            task: The plan or proposal to critique
            context: Optional context
            
        Returns:
            AgentResponse with critique
        """
        try:
            prompt = f"""Critically analyze this plan or proposal. Provide constructive criticism:

{task}

Consider:
1. Strengths - What's good about this approach?
2. Weaknesses - What could go wrong?
3. Risks - What are the potential failure points?
4. Alternatives - What other approaches should be considered?
5. Improvements - How could this be better?

Be direct and honest. It's better to find problems now than after implementation."""

            messages = self._format_messages(prompt, context)
            
            result = self._call_ollama(
                model=self.config.get_model_for_agent("debator"),
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
                metadata={"task": task[:50], "agent": "debator", "type": "critique"}
            )
            
        except Exception as e:
            return self._wrap_error(f"Debator agent error: {str(e)}")
    
    def debate(self, proposal: str, counter_arguments: Optional[List[str]] = None) -> AgentResponse:
        """
        Engage in a structured debate about a proposal.
        
        Args:
            proposal: The proposal to debate
            counter_arguments: Optional counter-arguments to address
            
        Returns:
            AgentResponse with debate outcome
        """
        counter_text = ""
        if counter_arguments:
            counter_text = "\n\nCounter-arguments to address:\n" + "\n".join(
                f"- {arg}" for arg in counter_arguments
            )
        
        prompt = f"""Engage in a structured debate about this proposal:

{proposal}
{counter_text}

Structure your response as:
1. Opening Position - Your stance on the proposal
2. Arguments For - Strongest points in favor
3. Arguments Against - Strongest points against
4. Counter-Rebuttals - Responses to counter-arguments
5. Verdict - Balanced assessment with recommendation

Take this seriously - good debate leads to better solutions."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("debator"),
            messages=messages,
            temperature=0.5
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "structured_debate"}
            )
        return self._wrap_error(result.get("error", "Failed to debate"))
    
    def challenge_assumptions(self, plan: str) -> AgentResponse:
        """
        Challenge the assumptions in a plan.
        
        Args:
            plan: The plan to analyze
            
        Returns:
            AgentResponse with identified assumptions
        """
        prompt = f"""Identify and challenge the assumptions in this plan:

{plan}

For each assumption:
1. State the assumption clearly
2. Question its validity
3. What would happen if it's wrong?
4. How could we verify this assumption?

Be skeptical but constructive."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("debator"),
            messages=messages,
            temperature=0.5
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "assumption_challenging"}
            )
        return self._wrap_error(result.get("error", "Failed to challenge assumptions"))
    
    def suggest_alternatives(self, current_approach: str, task: str) -> AgentResponse:
        """
        Suggest alternative approaches.
        
        Args:
            current_approach: The current approach being considered
            task: The overall task/goal
            
        Returns:
            AgentResponse with alternative approaches
        """
        prompt = f"""For this task: {task}

Current approach: {current_approach}

Suggest 3-5 alternative approaches, including:
1. What the approach is
2. Advantages over current approach
3. Disadvantages/PTradeoffs
4. When this approach would be best

Focus on genuinely different strategies, not minor variations."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("debator"),
            messages=messages,
            temperature=0.6  # Higher for creative alternatives
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "alternative_suggestions"}
            )
        return self._wrap_error(result.get("error", "Failed to suggest alternatives"))
    
    def evaluate_complexity(self, plan: str) -> AgentResponse:
        """
        Evaluate the complexity and risks of a plan.
        
        Args:
            plan: The plan to evaluate
            
        Returns:
            AgentResponse with complexity assessment
        """
        prompt = f"""Evaluate the complexity and risks of this plan:

{plan}

Assess:
1. Technical Complexity - How technically difficult is this?
2. Integration Complexity - How many moving parts need to work together?
3. Maintenance Complexity - How hard to maintain long-term?
4. Risk Factors - What could fail?
5. Risk Mitigation - How to reduce risks?

Be honest about tradeoffs."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("debator"),
            messages=messages,
            temperature=0.3
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "complexity_evaluation"}
            )
        return self._wrap_error(result.get("error", "Failed to evaluate complexity"))
    
    def review_code_quality(self, code: str, language: str = "python") -> AgentResponse:
        """
        Review code quality and provide critique.
        
        Args:
            code: Code to review
            language: Programming language
            
        Returns:
            AgentResponse with code review
        """
        prompt = f"""Critically review this {language} code:

{code}

Evaluate:
1. Correctness - Does it do what it's supposed to?
2. Code Quality - Is it clean, readable, well-structured?
3. Performance - Any obvious inefficiencies?
4. Security - Any potential security issues?
5. Best Practices - Does it follow language conventions?
6. Suggestions - Specific improvements

Be thorough but constructive."""

        messages = self._format_messages(prompt)
        
        result = self._call_ollama(
            model=self.config.get_model_for_agent("debator"),
            messages=messages,
            temperature=0.4
        )
        
        if result["success"]:
            return self._wrap_response(
                content=result["response"],
                metadata={"type": "code_review", "language": language}
            )
        return self._wrap_error(result.get("error", "Failed to review code"))
