import logging
from typing import Dict, List, Any, Optional
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class JudgmentModel:
    """Model for making a judgment based on multiple verification results."""
    
    def __init__(self, settings_model):
        """
        Initialize the judgment model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
    
    def make_judgment(self, email: str, results: List[EmailVerificationResult]) -> EmailVerificationResult:
        """
        Make a judgment based on multiple verification results.
        
        Args:
            email: The email address
            results: List of verification results
            
        Returns:
            EmailVerificationResult: The final judgment
        """
        if not results:
            # No results to judge
            logger.warning(f"No verification results to judge for {email}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason="No verification results available",
                provider="unknown"
            )
        
        # Count results by category
        counts = {
            VALID: 0,
            INVALID: 0,
            RISKY: 0,
            CUSTOM: 0
        }
        
        for result in results:
            counts[result.category] += 1
        
        # If we have any definitive results (valid or invalid), use the most recent one
        if counts[VALID] > 0:
            # Find the most recent valid result
            valid_results = [r for r in results if r.category == VALID]
            valid_results.sort(key=lambda r: r.timestamp, reverse=True)
            logger.info(f"Judgment for {email}: VALID (based on {valid_results[0].reason})")
            return valid_results[0]
        
        if counts[INVALID] > 0:
            # Find the most recent invalid result
            invalid_results = [r for r in results if r.category == INVALID]
            invalid_results.sort(key=lambda r: r.timestamp, reverse=True)
            logger.info(f"Judgment for {email}: INVALID (based on {invalid_results[0].reason})")
            return invalid_results[0]
        
        # If we only have risky or custom results, use the most recent one
        if counts[RISKY] > 0:
            # Find the most recent risky result
            risky_results = [r for r in results if r.category == RISKY]
            risky_results.sort(key=lambda r: r.timestamp, reverse=True)
            logger.info(f"Judgment for {email}: RISKY (based on {risky_results[0].reason})")
            return risky_results[0]
        
        if counts[CUSTOM] > 0:
            # Find the most recent custom result
            custom_results = [r for r in results if r.category == CUSTOM]
            custom_results.sort(key=lambda r: r.timestamp, reverse=True)
            logger.info(f"Judgment for {email}: CUSTOM (based on {custom_results[0].reason})")
            return custom_results[0]
        
        # This should never happen, but just in case
        logger.error(f"Could not make a judgment for {email}")
        return EmailVerificationResult(
            email=email,
            category=RISKY,
            reason="Could not make a judgment",
            provider="unknown"
        )
