from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime

# Email categories
VALID = "valid"
INVALID = "invalid"
RISKY = "risky"
CUSTOM = "custom"

@dataclass
class EmailVerificationResult:
    """Result of an email verification attempt."""
    email: str
    category: str  # valid, invalid, risky, custom
    reason: str
    provider: str
    details: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __str__(self) -> str:
        return f"{self.email}: {self.category} ({self.provider}) - {self.reason}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "email": self.email,
            "category": self.category,
            "reason": self.reason,
            "provider": self.provider,
            "details": self.details,
            "timestamp": self.timestamp
        }
