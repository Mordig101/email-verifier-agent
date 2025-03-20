import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class SequenceModel:
    """Model for determining the verification sequence based on provider."""
    
    def __init__(self, settings_model):
        """
        Initialize the sequence model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Define verification sequences for different providers
        self.verification_sequences = {
            # Microsoft verification: API → Selenium → SMTP
            'outlook.com': ['api', 'selenium', 'smtp'],
            'hotmail.com': ['api', 'selenium', 'smtp'],
            'live.com': ['api', 'selenium', 'smtp'],
            'microsoft.com': ['api', 'selenium', 'smtp'],
            'office365.com': ['api', 'selenium', 'smtp'],
            
            # Gmail verification: SMTP → Selenium
            'gmail.com': ['smtp', 'selenium'],
            
            # Custom Google provider (not gmail.com): Selenium → SMTP
            'customGoogle': ['selenium', 'smtp'],
            
            # Yahoo verification: Selenium → SMTP
            'yahoo.com': ['selenium', 'smtp'],
            
            # Default sequence for unknown providers: SMTP only
            'default': ['smtp']
        }
    
    def get_verification_sequence(self, provider: str) -> List[str]:
        """
        Get the verification sequence for a provider.
        
        Args:
            provider: The email provider
            
        Returns:
            List[str]: List of verification methods to try in order
        """
        # Check if we have a specific sequence for this provider
        if provider in self.verification_sequences:
            sequence = self.verification_sequences[provider]
        else:
            # Use default sequence for unknown providers
            sequence = self.verification_sequences['default']
        
        # Filter out disabled methods
        filtered_sequence = []
        for method in sequence:
            if method == 'api' and not self.settings_model.is_enabled('microsoft_api') and provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                # Skip API method if Microsoft API is disabled
                continue
            
            filtered_sequence.append(method)
        
        logger.info(f"Using verification sequence for {provider}: {filtered_sequence}")
        return filtered_sequence
