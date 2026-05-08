"""
Configuration for the Devin Agent system.
Handles model settings, API endpoints, and system parameters.
"""

import os
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_MODELS = {
    "architect": "ollama:llama3.2:latest",
    "coder": "ollama:llama3.2:latest",
    "tester": "ollama:mistral:latest",
    "fixer": "ollama:mistral:latest",
    "debator": "ollama:mistral:latest",
    "fallback": "ollama:mistral:latest",
}
LEGACY_DEFAULT_MODELS = {
    "architect": "openrouter:openrouter/free",
    "coder": "ollama:llama3.1:8b",
    "tester": "ollama:qwen3:4b",
    "fixer": "ollama:mistral:latest",
    "debator": "openrouter:openrouter/free",
    "fallback": "ollama:qwen3:4b",
}
LEGACY_PRIMARY_MODEL = "ollama:llama3.1:8b"

DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LEGACY_FALLBACK_MODELS = ["deepseek-r1:1.5b", "llama3.2:3b", "qwen3:4b"]
DEFAULT_FALLBACK_MODELS = [
    "ollama:mistral:latest",
    "ollama:llama3.2:latest",
    "openrouter:openrouter/free",
]
SLOW_FALLBACK_KEYWORDS = ("qwen",)
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_API_KEYS_SOURCE = str((Path.home() / "Desktop" / "API_KEYS_ALL").resolve())

DEFAULT_REMOTE_MODELS = {
    "openrouter": ["openrouter:openrouter/free"],
}

DEFAULT_AGENT_PROFILES = {
    "architect": {
        "temperature": 0.2,
        "timeout_seconds": 40,
        "max_tokens": 2000,
        "num_ctx": 8192,
    },
    "coder": {
        "temperature": 0.1,
        "timeout_seconds": 60,
        "max_tokens": 1800,
        "num_ctx": 8192,
    },
    "tester": {
        "temperature": 0.1,
        "timeout_seconds": 45,
        "max_tokens": 900,
        "num_ctx": 8192,
    },
    "fixer": {
        "temperature": 0.0,
        "timeout_seconds": 45,
        "max_tokens": 1200,
        "num_ctx": 8192,
    },
    "debator": {
        "temperature": 0.15,
        "timeout_seconds": 35,
        "max_tokens": 900,
        "num_ctx": 4096,
    },
    "fallback": {
        "temperature": 0.1,
        "timeout_seconds": 30,
        "max_tokens": 768,
        "num_ctx": 4096,
    },
}

DEFAULT_ALLOWED_COMMANDS = [
    "npm install",
    "npm run dev",
    "npm run build",
    "python",
    "pip install",
    "pip3 install",
    "uv pip install",
    "node",
    "git init",
    "git add .",
    "git commit -m",
    "git status",
    "dir",
    "ls",
    "ollama pull",
    "ollama rm",
]

DEFAULT_BLOCKED_COMMANDS = [
    "rm -rf",
    "del /f",
    "shutdown",
    "format",
    "powershell remove-item",
    "curl | sh",
    "wget | sh",
]


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    name: str
    temperature: float = 0.3
    max_tokens: int = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: Optional[List[str]] = None


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    model: str
    system_prompt: str = ""
    max_retries: int = 3
    timeout_seconds: int = 60
    temperature: float = 0.7
    max_tokens: int = 1024
    num_ctx: int = 2048
    enabled: bool = True


@dataclass
class GitConfig:
    """Git configuration."""

    auto_commit: bool = True
    commit_message_prefix: str = "Devin Agent:"
    auto_stage: bool = True
    branch_prefix: str = "devin/"
    max_history: int = 50


@dataclass
class MemoryConfig:
    """Memory system configuration."""

    storage_path: str = "~/.devin_agent/memory"
    max_entries: int = 1000
    context_window: int = 10
    auto_save: bool = True


@dataclass
class Config:
    """Main configuration for the Devin Agent system."""

    # Ollama settings
    ollama_host: str = DEFAULT_OLLAMA_HOST
    models: Dict[str, str] = field(default_factory=lambda: DEFAULT_MODELS.copy())

    # Ollama runtime defaults (used by dashboard chat + client utilities)
    ollama_primary_model: str = "ollama:llama3.2:latest"
    ollama_fallback_models: List[str] = field(
        default_factory=lambda: DEFAULT_FALLBACK_MODELS.copy()
    )
    ollama_max_context_tokens: int = 8192
    ollama_temperature: float = 0.1
    ollama_timeout_seconds: int = 60
    ollama_healing_timeout_seconds: int = 20
    ollama_healing_max_tokens: int = 1024
    ollama_streaming: bool = True
    ollama_enable_caching: bool = True
    ollama_cache_ttl_seconds: int = 300
    ollama_cache_max_entries: int = 200
    ollama_idle_timeout_minutes: int = 15
    groq_enabled: bool = False
    groq_base_url: str = DEFAULT_GROQ_BASE_URL
    openai_enabled: bool = False
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    openrouter_enabled: bool = True
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE_URL
    api_keys_source_path: str = DEFAULT_API_KEYS_SOURCE
    provider_catalog_models: Dict[str, List[str]] = field(
        default_factory=lambda: {
            key: value.copy() for key, value in DEFAULT_REMOTE_MODELS.items()
        }
    )
    model_warmup_enabled: bool = True
    model_warmup_timeout_seconds: int = 20
    model_warmup_prompt: str = "Reply with OK only."
    groq_api_key: Optional[str] = field(default=None, repr=False)
    openai_api_key: Optional[str] = field(default=None, repr=False)
    openrouter_api_key: Optional[str] = field(default=None, repr=False)

    # Offline-first
    offline_queue_enabled: bool = True
    offline_queue_requests: bool = True

    # Agent configurations
    agent_configs: Dict[str, AgentConfig] = field(default_factory=dict)

    # Git settings
    git: GitConfig = field(default_factory=GitConfig)

    # Memory settings
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    # Execution settings
    max_iterations: int = 100
    iteration_delay: float = 1.0
    self_heal_enabled: bool = True
    max_heal_attempts: int = 3

    # CLI settings
    verbose: bool = False
    color_enabled: bool = True
    workspace_root: str = "."

    # Task routing
    complexity_threshold_simple: int = 5
    complexity_threshold_medium: int = 15
    allowed_commands: List[str] = field(
        default_factory=lambda: DEFAULT_ALLOWED_COMMANDS.copy()
    )
    blocked_commands: List[str] = field(
        default_factory=lambda: DEFAULT_BLOCKED_COMMANDS.copy()
    )

    def __post_init__(self):
        """Initialize default agent configurations."""
        self._load_external_provider_keys()
        if not self.agent_configs:
            for agent_name, model_name in self.models.items():
                profile = DEFAULT_AGENT_PROFILES.get(
                    agent_name, DEFAULT_AGENT_PROFILES["fallback"]
                )
                self.agent_configs[agent_name] = AgentConfig(
                    model=model_name,
                    system_prompt=self._get_default_system_prompt(agent_name),
                    temperature=profile["temperature"],
                    timeout_seconds=profile["timeout_seconds"],
                    max_tokens=profile["max_tokens"],
                    num_ctx=profile["num_ctx"],
                )

    def _get_default_system_prompt(self, agent_name: str) -> str:
        """Get default system prompt for an agent type."""
        core = """[CORE DIRECTIVE]
You are a specialized node within a 5-part Autonomous AI Engineering Swarm.
Primary implementation language is Python.
You build scalable, secure, and efficient systems.
You do not hallucinate dependencies; you verify them before using them.

[TEAM ROLES]
- ARCHITECT: system design, infrastructure, and security planning.
- CODER: implementation, algorithm development, and script creation.
- TESTER: QA, defensive security auditing, and test generation.
- FIXER: traceback analysis, targeted patching, and optimization.
- DEBATOR: code review, assumption challenge, and edge-case prediction.
"""
        prompts = {
            "architect": """# ROLE: ARCHITECT
You are the Architect agent.

Your job:
- Break the user request into clear steps
- Define file structure
- Specify exact files to create or edit
- Output commands to run

Rules:
- Output JSON only
- Be deterministic and structured
- No explanations

Format:
{
  "steps": [],
  "files": [
    {
      "path": "",
      "action": "create|edit",
      "description": ""
    }
  ],
  "commands": []
}
""",
            "coder": """# ROLE: CODER
You are the Coder agent.

Your job:
- Create or edit files exactly as instructed
- Follow file paths strictly

Rules:
- Output only code or file content
- If editing, output the full file
- No explanations
- No markdown

If multiple files:
===FILE: path/to/file===
<content>
===END===
""",
            "tester": """# ROLE: TESTER
## SYSTEM_CONTEXT
You are the quality assurance and defensive security auditor.

Your job:
- Validate functionality and scope compliance
- Test malformed input, timeouts, and 403/429 handling
- Log reproducible failures for Fixer

Rules:
- Be concise
- Report pass/fail evidence
- Include exact reproduction steps for failures
- Do not rewrite unless a critical blocker prevents testing
""",
            "fixer": """# ROLE: FIXER
You are the Fixer agent.

Your job:
- Analyze errors
- Fix broken code
- Improve reliability

Rules:
- Output full corrected files
- Do not explain unless necessary
- Keep changes minimal

Focus:
- Syntax errors
- Runtime issues
- Missing dependencies
""",
            "debator": """# ROLE: DEBATOR
## SYSTEM_CONTEXT
You are the final logic challenger and future-proofing reviewer.

Your job:
- Review final output for hidden flaws and edge cases
- Challenge assumptions, ethics, OPSEC, and long-term risks
- Suggest safer or simpler alternatives before approval

Rules:
- Be direct and specific
- Separate blockers from improvements
- Future-proof the result without changing the agreed architecture
""",
        }
        role_prompt = prompts.get(agent_name, f"You are a {agent_name} agent.")
        return f"{core}\n{role_prompt}"

    def _load_external_provider_keys(self) -> None:
        env_openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        env_openrouter_base = (
            os.getenv("OPENROUTER_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
        ).strip()
        env_openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        env_openai_base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        env_groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        env_groq_base = (os.getenv("GROQ_BASE_URL") or "").strip()

        # Environment-driven boolean overrides (useful on Railway)
        if os.getenv("MODEL_WARMUP_ENABLED") is not None:
            self.model_warmup_enabled = os.getenv("MODEL_WARMUP_ENABLED", "").lower() in ("1", "true", "yes")
        if os.getenv("OFFLINE_QUEUE_ENABLED") is not None:
            self.offline_queue_enabled = os.getenv("OFFLINE_QUEUE_ENABLED", "").lower() in ("1", "true", "yes")
        if os.getenv("OFFLINE_QUEUE_REQUESTS") is not None:
            self.offline_queue_requests = os.getenv("OFFLINE_QUEUE_REQUESTS", "").lower() in ("1", "true", "yes")

        if env_openrouter_key:
            self.openrouter_api_key = env_openrouter_key
        if env_openrouter_base:
            self.openrouter_base_url = env_openrouter_base.rstrip("/")
        if env_openai_key:
            self.openai_api_key = env_openai_key
        if env_openai_base:
            self.openai_base_url = env_openai_base.rstrip("/")
        if env_groq_key:
            self.groq_api_key = env_groq_key
        if env_groq_base:
            self.groq_base_url = env_groq_base.rstrip("/")

        source_dir = Path(self.api_keys_source_path).expanduser()
        if not source_dir.exists() or not source_dir.is_dir():
            return

        if self.openrouter_enabled and not self.openrouter_api_key:
            self.openrouter_api_key = self._extract_key_from_folder(
                source_dir,
                "openrouter",
                r"(sk-or-v1-[A-Za-z0-9_\-]+)",
            )
        if self.groq_enabled and not self.groq_api_key:
            self.groq_api_key = self._extract_key_from_folder(
                source_dir, "groq", r"(gsk_[A-Za-z0-9]+)"
            )
        if self.openai_enabled and not self.openai_api_key:
            self.openai_api_key = self._extract_key_from_folder(
                source_dir, "openai", r"(sk-proj-[A-Za-z0-9_\-]+)"
            )

    @staticmethod
    def _extract_key_from_folder(
        source_dir: Path, name_hint: str, pattern: str
    ) -> Optional[str]:
        regex = re.compile(pattern)
        candidates = sorted(source_dir.glob("*"))
        preferred = [
            path for path in candidates if name_hint.lower() in path.name.lower()
        ]
        ordered = preferred + [path for path in candidates if path not in preferred]
        for path in ordered:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            match = regex.search(content)
            if match:
                return match.group(1)
        return None

    @classmethod
    def load(cls, path: str) -> "Config":
        """Load configuration from a JSON file."""
        config_path = Path(path).expanduser()
        if config_path.exists():
            with open(config_path, "r") as f:
                data = json.load(f)
            return cls.from_dict(data)
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from a dictionary."""
        git_data = data.pop("git", {})
        memory_data = data.pop("memory", {})
        agent_configs_data = data.pop("agent_configs", {})
        raw_fallback_models = data.get("ollama_fallback_models")
        if data.get("models") == LEGACY_DEFAULT_MODELS:
            data["models"] = DEFAULT_MODELS.copy()
        if data.get("ollama_primary_model") == LEGACY_PRIMARY_MODEL:
            data["ollama_primary_model"] = Config.ollama_primary_model
        if raw_fallback_models == LEGACY_FALLBACK_MODELS:
            raw_fallback_models = DEFAULT_FALLBACK_MODELS.copy()
        if isinstance(raw_fallback_models, list):
            cleaned = []
            seen = set()
            for name in raw_fallback_models:
                if not name or name in seen:
                    continue
                seen.add(name)
                lowered = str(name).lower()
                if any(keyword in lowered for keyword in SLOW_FALLBACK_KEYWORDS):
                    continue
                cleaned.append(name)
            data["ollama_fallback_models"] = cleaned or DEFAULT_FALLBACK_MODELS.copy()

        config = cls(**data)
        config.git = GitConfig(**git_data)
        config.memory = MemoryConfig(**memory_data)
        config.agent_configs = {
            k: AgentConfig(**v) if isinstance(v, dict) else v
            for k, v in agent_configs_data.items()
        }
        return config

    def to_dict(self) -> dict:
        """Convert Config to a dictionary."""
        return {
            "ollama_host": self.ollama_host,
            "models": self.models,
            "ollama_primary_model": self.ollama_primary_model,
            "ollama_fallback_models": self.ollama_fallback_models,
            "ollama_max_context_tokens": self.ollama_max_context_tokens,
            "ollama_temperature": self.ollama_temperature,
            "ollama_timeout_seconds": self.ollama_timeout_seconds,
            "ollama_healing_timeout_seconds": self.ollama_healing_timeout_seconds,
            "ollama_healing_max_tokens": self.ollama_healing_max_tokens,
            "ollama_streaming": self.ollama_streaming,
            "ollama_enable_caching": self.ollama_enable_caching,
            "ollama_cache_ttl_seconds": self.ollama_cache_ttl_seconds,
            "ollama_cache_max_entries": self.ollama_cache_max_entries,
            "ollama_idle_timeout_minutes": self.ollama_idle_timeout_minutes,
            "groq_enabled": self.groq_enabled,
            "groq_base_url": self.groq_base_url,
            "openai_enabled": self.openai_enabled,
            "openai_base_url": self.openai_base_url,
            "openrouter_enabled": self.openrouter_enabled,
            "openrouter_base_url": self.openrouter_base_url,
            "api_keys_source_path": self.api_keys_source_path,
            "provider_catalog_models": self.provider_catalog_models,
            "model_warmup_enabled": self.model_warmup_enabled,
            "model_warmup_timeout_seconds": self.model_warmup_timeout_seconds,
            "model_warmup_prompt": self.model_warmup_prompt,
            "offline_queue_enabled": self.offline_queue_enabled,
            "offline_queue_requests": self.offline_queue_requests,
            "git": self.git.__dict__,
            "memory": self.memory.__dict__,
            "agent_configs": {
                k: v.__dict__ if hasattr(v, "__dict__") else v
                for k, v in self.agent_configs.items()
            },
            "max_iterations": self.max_iterations,
            "iteration_delay": self.iteration_delay,
            "self_heal_enabled": self.self_heal_enabled,
            "max_heal_attempts": self.max_heal_attempts,
            "verbose": self.verbose,
            "color_enabled": self.color_enabled,
            "workspace_root": self.workspace_root,
            "complexity_threshold_simple": self.complexity_threshold_simple,
            "complexity_threshold_medium": self.complexity_threshold_medium,
            "allowed_commands": self.allowed_commands,
            "blocked_commands": self.blocked_commands,
        }

    def save(self, path: str):
        """Save configuration to a JSON file."""
        config_path = Path(path).expanduser()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_model_for_agent(self, agent_name: str) -> str:
        """Get the model name for a specific agent."""
        return self.models.get(
            agent_name, self.models.get("fallback", "ollama:mistral:latest")
        )


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config):
    """Set the global configuration instance."""
    global _config
    _config = config
