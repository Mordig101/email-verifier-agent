import re
import dns.resolver
import logging
from typing import Dict, List, Optional, Tuple, Any
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class InitialValidationModel:
    """Model for initial email validation and provider identification."""
    
    def __init__(self, settings_model):
        """
        Initialize the initial validation model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Cache for MX records
        self.mx_cache: Dict[str, List[str]] = {}
        
        # Known email providers and their login URLs
        self.provider_login_urls = {
            # Major providers
            'gmail.com': 'https://accounts.google.com/v3/signin/identifier?checkedDomains=youtube&continue=https%3A%2F%2Faccounts.google.com%2F&ddm=1&flowEntry=ServiceLogin&flowName=GlifWebSignIn&followup=https%3A%2F%2Faccounts.google.com%2F&ifkv=ASSHykqZwmsZ-Y8kMUy1FaZIF_roUjdswunM1zU1MHwMol0ScsWw6Ccfrnl6CF5AGNdJYnPIXWCAag&pstMsg=1&dsh=S-618504277%3A1741397881564214',
            'googlemail.com': 'https://accounts.google.com/v3/signin/identifier?flowName=GlifWebSignIn',
            'outlook.com': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?scope=service%3A%3Aaccount.microsoft.com%3A%3AMBI_SSL+openid+profile+offline_access&response_type=code&client_id=81feaced-5ddd-41e7-8bef-3e20a2689bb7&redirect_uri=https%3A%2F%2Faccount.microsoft.com%2Fauth%2Fcomplete-signin-oauth&client-request-id=91a4ca34-664d-4f85-b023-b815182d057e&x-client-SKU=MSAL.Desktop&x-client-Ver=4.66.1.0&x-client-OS=Windows+Server+2019+Datacenter&prompt=login&client_info=1&state=H4sIAAAAAAAEAA3OR4KCMAAAwL945QBoKB48gAhGTUKVcpOyUgIIIlnz-t15wWxOkdgndzKKgzSP0sPvj6ylebkaJnlzK-s0zslzEDxJW0UhHvEoa8gondYS2LTTFj8N67QGK0Xnl7SoUWRXezriNbboRIRAH11HDqhyTBouvKsZMdgD_EwXpH2sZhExKJfvafuKxXbvtGmo4JABCBsFdIXfz1A5ReoS5TaufobXzFD27PSPwvn1JjnTMNvUIxAhZIvJMrxonWBPzz_q-cwoGpZMT_dt0HJwoQjGbICKmRvY9fjN_a9X83yN15D0QONFuUsucuoQrfbvd--XVEViWqUbRJXAOukcyRNmjUoyrhYWNEAvdQbMsp2XArl4F9vEzh95s3fGb2Q-Hs2VHQ6bP6JJZGZaAQAA&msaoauth2=true&lc=1036&sso_reload=true',
            'hotmail.com': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?scope=service%3A%3Aaccount.microsoft.com%3A%3AMBI_SSL+openid+profile+offline_access&response_type=code&client_id=81feaced-5ddd-41e7-8bef-3e20a2689bb7&redirect_uri=https%3A%2F%2Faccount.microsoft.com%2Fauth%2Fcomplete-signin-oauth&client-request-id=91a4ca34-664d-4f85-b023-b815182d057e&x-client-SKU=MSAL.Desktop&x-client-Ver=4.66.1.0&x-client-OS=Windows+Server+2019+Datacenter&prompt=login&client_info=1&state=H4sIAAAAAAAEAA3OR4KCMAAAwL945QBoKB48gAhGTUKVcpOyUgIIIlnz-t15wWxOkdgndzKKgzSP0sPvj6ylebkaJnlzK-s0zslzEDxJW0UhHvEoa8gondYS2LTTFj8N67QGK0Xnl7SoUWRXezriNbboRIRAH11HDqhyTBouvKsZMdgD_EwXpH2sZhExKJfvafuKxXbvtGmo4JABCBsFdIXfz1A5ReoS5TaufobXzFD27PSPwvn1JjnTMNvUIxAhZIvJMrxonWBPzz_q-cwoGpZMT_dt0HJwoQjGbICKmRvY9fjN_a9X83yN15D0QONFuUsucuoQrfbvd--XVEViWqUbRJXAOukcyRNmjUoyrhYWNEAvdQbMsp2XArl4F9vEzh95s3fGb2Q-Hs2VHQ6bP6JJZGZaAQAA&msaoauth2=true&lc=1036&sso_reload=true',
            'live.com': 'https://login.live.com',
            'yahoo.com': 'https://login.yahoo.com',
            'aol.com': 'https://login.aol.com',
            'protonmail.com': 'https://mail.proton.me/login',
            'zoho.com': 'https://accounts.zoho.com/signin',
            
            # Regional providers
            'mail.ru': 'https://account.mail.ru/login',
            'yandex.ru': 'https://passport.yandex.ru/auth',
            
            # Corporate providers often use Microsoft or Google
            'microsoft.com': 'https://login.microsoftonline.com',
            'office365.com': 'https://login.microsoftonline.com',
        }
    
    def validate_format(self, email: str) -> bool:
        """
        Check if the email has a valid format.
        
        Args:
            email: The email address to validate
            
        Returns:
            bool: True if the email format is valid, False otherwise
        """
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def get_mx_records(self, domain: str) -> List[str]:
        """
        Get MX records for a domain to identify the mail provider.
        
        Args:
            domain: The domain to get MX records for
            
        Returns:
            List[str]: List of MX server hostnames
        """
        # Check cache first
        if domain in self.mx_cache:
            return self.mx_cache[domain]
            
        try:
            records = dns.resolver.resolve(domain, 'MX', lifetime=5)
            mx_servers = [str(x.exchange).rstrip('.').lower() for x in records]
            
            # Cache the result
            self.mx_cache[domain] = mx_servers
                
            return mx_servers
        except Exception as e:
            logger.warning(f"Error getting MX records for {domain}: {e}")
            return []
    
    def identify_provider(self, email: str) -> Tuple[str, str]:
        """
        Identify the email provider based on the domain and MX records.
        
        Args:
            email: The email address to identify the provider for
            
        Returns:
            Tuple[str, str]: (provider_name, login_url)
        """
        _, domain = email.split('@')
        
        # Check if it's a known provider
        if domain in self.provider_login_urls:
            return domain, self.provider_login_urls[domain]
        
        # Check MX records to identify the provider
        mx_records = self.get_mx_records(domain)
        
        # Look for known providers in MX records
        for mx in mx_records:
            if 'google' in mx or 'gmail' in mx:
                if domain == 'gmail.com':
                    return 'gmail.com', self.provider_login_urls['gmail.com']
                else:
                    # Mark as customGoogle for other Google-hosted domains
                    return 'customGoogle', self.provider_login_urls['gmail.com']
            elif 'outlook' in mx or 'microsoft' in mx or 'office365' in mx:
                return 'outlook.com', self.provider_login_urls['outlook.com']
            elif 'yahoo' in mx:
                return 'yahoo.com', self.provider_login_urls['yahoo.com']
            elif 'protonmail' in mx or 'proton.me' in mx:
                return 'protonmail.com', self.provider_login_urls['protonmail.com']
            elif 'zoho' in mx:
                return 'zoho.com', self.provider_login_urls['zoho.com']
            elif 'mail.ru' in mx:
                return 'mail.ru', self.provider_login_urls['mail.ru']
            elif 'yandex' in mx:
                return 'yandex.ru', self.provider_login_urls['yandex.ru']
        
        # If we can't identify the provider, it's a custom domain
        return 'custom', None
    
    def validate_email(self, email: str) -> Optional[EmailVerificationResult]:
        """
        Perform initial validation of an email address.
        
        Args:
            email: The email address to validate
            
        Returns:
            Optional[EmailVerificationResult]: Validation result or None if validation passed
        """
        # Step 1: Validate email format
        if not self.validate_format(email):
            logger.warning(f"Invalid email format: {email}")
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Invalid email format",
                provider="unknown"
            )
        
        # Extract domain
        _, domain = email.split('@')
        
        # Step 2: Check if domain is blacklisted
        if domain in self.settings_model.get_blacklisted_domains():
            logger.info(f"Domain is blacklisted: {domain}")
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Domain is blacklisted",
                provider=domain
            )
        
        # Step 3: Check if domain should be skipped (whitelisted)
        if domain in self.settings_model.get_whitelisted_domains():
            logger.info(f"Domain in whitelist: {domain}")
            return EmailVerificationResult(
                email=email,
                category=VALID,
                reason="Domain in whitelist",
                provider=domain
            )
        
        # Step 4: Check MX records
        mx_records = self.get_mx_records(domain)
        
        if not mx_records:
            logger.warning(f"Domain has no mail servers: {domain}")
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Domain has no mail servers",
                provider="unknown"
            )
        
        # If all validation checks pass, return None to continue with verification
        return None
