import requests
import logging
import time
import random
from typing import Dict, List, Any, Optional
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class APIModel:
    """Model for API-based email verification."""
    
    def __init__(self, settings_model):
        """
        Initialize the API model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Rate limiter will be initialized by the controller
        self.rate_limiter = None
    
    def set_rate_limiter(self, rate_limiter):
        """
        Set the rate limiter.
        
        Args:
            rate_limiter: The rate limiter instance
        """
        self.rate_limiter = rate_limiter
    
    def verify_microsoft_api(self, email: str) -> Optional[EmailVerificationResult]:
        """
        Verify Microsoft email using the GetCredentialType API.
        
        Args:
            email: The email address to verify
            
        Returns:
            Optional[EmailVerificationResult]: The verification result, or None if inconclusive
        """
        if not self.settings_model.is_enabled("microsoft_api"):
            return None
        
        logger.info(f"Microsoft API verification started for {email}")
        
        # Extract domain for rate limiting
        _, domain = email.split('@')
        
        # Check rate limiting if rate limiter is set
        if self.rate_limiter and self.rate_limiter.is_rate_limited(domain):
            wait_time = self.rate_limiter.get_backoff_time(domain)
            logger.info(f"Microsoft API verification rate limited for {domain}, waiting {wait_time}s")
            time.sleep(wait_time)
            
            # Record this request
            if self.rate_limiter:
                self.rate_limiter.add_request(domain)
        
        # Check for catch-all domain using API
        is_catch_all = self._check_microsoft_catch_all(domain)
        if is_catch_all:
            logger.info(f"Microsoft API verification detected catch-all domain: {domain}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason="Domain has catch-all configuration (Microsoft API)",
                provider="Microsoft",
                details={"is_catch_all": True}
            )
            
        try:
            # Set up a session with proxy if enabled
            session = requests.Session()
            if self.settings_model.is_enabled("proxy_enabled"):
                proxies = self.settings_model.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    session.proxies = {
                        "http": proxy,
                        "https": proxy
                    }
            
            # Set headers to look like a browser
            headers = {
                'User-Agent': self._get_random_user_agent(),
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://login.microsoftonline.com/',
                'Content-Type': 'application/json',
                'Origin': 'https://login.microsoftonline.com',
            }
            
            # Prepare the request payload
            payload = {
                'Username': email,
                'isOtherIdpSupported': True,
                'checkPhones': False,
                'isRemoteNGCSupported': True,
                'isCookieBannerShown': False,
                'isFidoSupported': True,
                'originalRequest': '',
                'country': 'US',
                'forceotclogin': False,
                'isExternalFederationDisallowed': False,
                'isRemoteConnectSupported': False,
                'federationFlags': 0,
                'isSignup': False,
                'flowToken': '',
                'isAccessPassSupported': True
            }
            
            # Make the request with retry logic
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    response = session.post(
                        'https://login.microsoftonline.com/common/GetCredentialType',
                        headers=headers,
                        json=payload,
                        timeout=10
                    )
                    break
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = 2 ** retry_count  # Exponential backoff
                        logger.warning(f"Network error with Microsoft API, retrying in {wait_time}s: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Max retries reached for Microsoft API: {str(e)}")
                        logger.info(f"Microsoft API verification error for {email}: {str(e)}")
                        return None
            
            # Check if the response indicates the email exists
            if response.status_code == 200:
                data = response.json()
                
                # Check for specific indicators in the response
                if 'IfExistsResult' in data:
                    if data['IfExistsResult'] == 0:
                        # 0 indicates the email exists
                        logger.info(f"Microsoft API verification result for {email}: VALID (Email address exists)")
                        return EmailVerificationResult(
                            email=email,
                            category=VALID,
                            reason="Email address exists (Microsoft API)",
                            provider="Microsoft",
                            details={"response": data}
                        )
                    elif data['IfExistsResult'] == 1:
                        # 1 indicates the email doesn't exist
                        logger.info(f"Microsoft API verification result for {email}: INVALID (Email address does not exist)")
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason="Email address does not exist (Microsoft API)",
                            provider="Microsoft",
                            details={"response": data}
                        )
                
                # If ThrottleStatus is in the response, the account might exist
                if 'ThrottleStatus' in data and data['ThrottleStatus'] == 1:
                    # We're being throttled, set a backoff
                    if self.rate_limiter:
                        self.rate_limiter.set_backoff(domain, 60)  # 1 minute backoff
                    logger.info(f"Microsoft API verification result for {email}: INCONCLUSIVE (Throttled)")
                    return None
            
            # If we can't determine from the response, return None to fall back to other methods
            logger.info(f"Microsoft API verification result for {email}: INCONCLUSIVE")
            return None
        
        except Exception as e:
            logger.error(f"Error verifying Microsoft email via API {email}: {e}")
            logger.info(f"Microsoft API verification error for {email}: {str(e)}")
            return None
    
    def _check_microsoft_catch_all(self, domain: str) -> bool:
        """
        Check if a domain has a catch-all email configuration using Microsoft API.
        
        Args:
            domain: The domain to check
            
        Returns:
            bool: True if it's a catch-all domain, False otherwise
        """
        # Generate a random email that almost certainly doesn't exist
        random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))
        test_email = f"{random_str}@{domain}"
        
        # Generate a real-looking email for the domain
        real_email = f"email@{domain}"
        
        # Try to verify both emails
        try:
            # Set up a session with proxy if enabled
            session = requests.Session()
            if self.settings_model.is_enabled("proxy_enabled"):
                proxies = self.settings_model.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    session.proxies = {
                        "http": proxy,
                        "https": proxy
                    }
            
            # Set headers to look like a browser
            headers = {
                'User-Agent': self._get_random_user_agent(),
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://login.microsoftonline.com/',
                'Content-Type': 'application/json',
                'Origin': 'https://login.microsoftonline.com',
            }
            
            # Check the random email
            random_payload = {
                'Username': test_email,
                'isOtherIdpSupported': True,
                'checkPhones': False,
                'isRemoteNGCSupported': True,
                'isCookieBannerShown': False,
                'isFidoSupported': True,
                'originalRequest': '',
                'country': 'US',
                'forceotclogin': False,
                'isExternalFederationDisallowed': False,
                'isRemoteConnectSupported': False,
                'federationFlags': 0,
                'isSignup': False,
                'flowToken': '',
                'isAccessPassSupported': True
            }
            
            random_response = session.post(
                'https://login.microsoftonline.com/common/GetCredentialType',
                headers=headers,
                json=random_payload,
                timeout=10
            )
            
            # Add a delay between requests
            time.sleep(random.uniform(2, 4))
            
            # Check the real-looking email
            real_payload = {
                'Username': real_email,
                'isOtherIdpSupported': True,
                'checkPhones': False,
                'isRemoteNGCSupported': True,
                'isCookieBannerShown': False,
                'isFidoSupported': True,
                'originalRequest': '',
                'country': 'US',
                'forceotclogin': False,
                'isExternalFederationDisallowed': False,
                'isRemoteConnectSupported': False,
                'federationFlags': 0,
                'isSignup': False,
                'flowToken': '',
                'isAccessPassSupported': True
            }
            
            real_response = session.post(
                'https://login.microsoftonline.com/common/GetCredentialType',
                headers=headers,
                json=real_payload,
                timeout=10
            )
            
            # Check if both responses indicate the emails exist
            if random_response.status_code == 200 and real_response.status_code == 200:
                random_data = random_response.json()
                real_data = real_response.json()
                
                # Check if both emails are reported as valid
                random_valid = 'IfExistsResult' in random_data and random_data['IfExistsResult'] == 0
                real_valid = 'IfExistsResult' in real_data and real_data['IfExistsResult'] == 0
                
                # If both random and real-looking emails are reported as valid, it's likely a catch-all
                if random_valid and real_valid:
                    logger.info(f"Microsoft API detected catch-all domain: {domain}")
                    return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error checking Microsoft catch-all for domain {domain}: {e}")
            return False
    
    def verify_google_api(self, email: str) -> Optional[EmailVerificationResult]:
        """
        Verify Google email using Google's API.
        
        Args:
            email: The email address to verify
            
        Returns:
            Optional[EmailVerificationResult]: The verification result, or None if inconclusive
        """
        # Google doesn't have a public API for email verification
        # This is a placeholder for future implementation
        logger.info(f"Google API verification not implemented for {email}")
        return None
    
    def verify_generic_api(self, email: str, provider: str) -> Optional[EmailVerificationResult]:
        """
        Verify email using a generic API.
        
        Args:
            email: The email address to verify
            provider: The email provider
            
        Returns:
            Optional[EmailVerificationResult]: The verification result, or None if inconclusive
        """
        # This is a placeholder for future implementation
        logger.info(f"Generic API verification not implemented for {email}")
        return None
    
    def _get_random_user_agent(self) -> str:
        """
        Get a random user agent to avoid detection.
        
        Returns:
            str: A random user agent string
        """
        user_agents = [
            #'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/122.0.0.0',
        ]
        return random.choice(user_agents)