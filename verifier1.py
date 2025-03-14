import re
import csv
import os
import dns.resolver
import logging
import time
import random
import socket
import smtplib
import requests
import json
import threading
import queue
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException

# Import settings
try:
    from settings.settings import Settings
except ImportError:
    # For relative imports when running as a package
    from .settings.settings import Settings

# Configure logging with more detailed format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Email categories
VALID = "valid"
INVALID = "invalid"
RISKY = "risky"
CUSTOM = "custom"

# Load settings
settings = Settings()

# Create screenshots directory
SCREENSHOTS_DIR = settings.get("screenshot_location", "./screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

@dataclass
class EmailVerificationResult:
    email: str
    category: str  # valid, invalid, risky, custom
    reason: str
    provider: str
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return f"{self.email}: {self.category} ({self.provider}) - {self.reason}"

class ImprovedLoginVerifier:
    def __init__(self, output_dir="./results", skip_domains=None):
        # Create output directory if it doesn't exist
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize skip domains
        self.skip_domains = skip_domains or []
        
        # Add domains from whitelist
        self.skip_domains.extend(settings.get_whitelisted_domains())
        
        # Initialize CSV files
        self.csv_files = {
            VALID: os.path.join(output_dir, "valid_emails.csv"),
            INVALID: os.path.join(output_dir, "invalid_emails.csv"),
            RISKY: os.path.join(output_dir, "risky_emails.csv"),
            CUSTOM: os.path.join(output_dir, "custom_emails.csv"),
        }
        
        # Create CSV files with headers if they don't exist
        for category, file_path in self.csv_files.items():
            if not os.path.exists(file_path):
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Email", "Provider", "Reason", "Details"])
        
        # Cache for verification results
        self.result_cache: Dict[str, EmailVerificationResult] = {}
        
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
        
        # Error messages that indicate an email doesn't exist
        self.nonexistent_email_phrases = {
            # Google
            'gmail.com': [
                "couldn't find your google account",
                "couldn't find your account",
                "no account found with that email",
                "couldn't find an account with that email"
            ],
            # Microsoft
            'outlook.com': [
                "we couldn't find an account with that username",
                "that microsoft account doesn't exist",
                "no account found",
                "this username may be incorrect",
                "ce nom d'utilisateur est peut-être incorrect"
            ],
            # Yahoo
            'yahoo.com': [
                "we couldn't find this account",
                "we don't recognize this email",
                "no account exists with this email address",
                "désolé, nous ne reconnaissons pas cette adresse mail"
            ],
            # Generic phrases that many providers use
            'generic': [
                "email not found",
                "user not found",
                "account not found",
                "no account",
                "doesn't exist",
                "invalid email",
                "email address is incorrect"
            ]
        }
        
        # Google-specific URL patterns for different states
        self.google_url_patterns = {
            'identifier': '/signin/identifier',  # Initial login page
            'pwd_challenge': '/signin/challenge/pwd',  # Password page (valid email)
            'rejected': '/signin/rejected',  # Security issue or rate limiting, not necessarily invalid
            'captcha': '/signin/v2/challenge/ipp',  # CAPTCHA challenge
            'security_challenge': '/signin/challenge',  # Other security challenges
            'TwoAcount':'signin/shadowdisambiguate?'
        }
        
        # Provider-specific page changes that indicate valid emails
        self.valid_email_indicators = {
            'gmail.com': {
                'heading_changes': {
                    'before': ['Sign in'],
                    'after': ['Welcome']
                },
                'url_patterns': {
                    'before': '/signin/identifier',
                    'after': '/signin/challenge/pwd'
                }
            },
            'outlook.com': {
                'heading_changes': {
                    'before': ['Sign in', 'Se connecter'],
                    'after': ['Enter password', 'Entrez le mot de passe']
                }
            }
        }
        
        # Next button text in different languages
        self.next_button_texts = [
            "Next", "Suivant", "Continuer", "Continue", "Weiter", 
            "Siguiente", "Próximo", "Avanti", "Volgende", "Далее",
            "下一步", "次へ", "다음", "التالي", "Tiếp theo"
        ]
        
        # Microsoft multi-account text indicators
        self.microsoft_multi_account_phrases = [
            "Il semble que ce courriel est utilisé avec plus d'un compte Microsoft",
            "Nous rencontrons des problèmes pour localiser votre compte",
            "This email is used with more than one account",
            "We're having trouble locating your account"
        ]
        
        # Initialize browser options for different browsers
        self._init_browser_options()
        
        # User agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15'
        ]
        
        # Cache for MX records
        self.mx_cache: Dict[str, List[str]] = {}
        
        # Multi-terminal support
        self.multi_terminal_enabled = settings.is_enabled("multi_terminal_enabled")
        self.terminal_count = settings.get_terminal_count()
        self.email_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.terminal_threads = []
        
        # Verification loop
        self.verification_loop_enabled = settings.is_enabled("verification_loop_enabled")

    def _init_browser_options(self):
        """Initialize browser options for different browsers."""
        # Chrome options
        self.chrome_options = ChromeOptions()
        self.chrome_options.add_argument("--incognito")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option("useAutomationExtension", False)
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "autofill.profile_enabled": False,
            "autofill.credit_card_enabled": False
        }
        self.chrome_options.add_experimental_option("prefs", prefs)
        
        # Edge options
        self.edge_options = EdgeOptions()
        self.edge_options.add_argument("--incognito")
        self.edge_options.add_argument("--no-sandbox")
        self.edge_options.add_argument("--disable-dev-shm-usage")
        self.edge_options.add_argument("--disable-gpu")
        self.edge_options.add_argument("--window-size=1920,1080")
        self.edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.edge_options.add_experimental_option("useAutomationExtension", False)
        self.edge_options.add_experimental_option("prefs", prefs)
        
        # Firefox options
        self.firefox_options = FirefoxOptions()
        self.firefox_options.add_argument("--private")
        self.firefox_options.add_argument("--no-sandbox")
        self.firefox_options.add_argument("--disable-dev-shm-usage")
        self.firefox_options.add_argument("--width=1920")
        self.firefox_options.add_argument("--height=1080")
        self.firefox_options.set_preference("dom.webnotifications.enabled", False)
        self.firefox_options.set_preference("browser.privatebrowsing.autostart", True)

    

    def get_random_user_agent(self) -> str:
        """Get a random user agent to avoid detection."""
        return random.choice(self.user_agents)

    def validate_format(self, email: str) -> bool:
        """Check if the email has a valid format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def get_mx_records(self, domain: str) -> List[str]:
        """Get MX records for a domain to identify the mail provider."""
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
        Returns (provider_name, login_url)
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
                return 'gmail.com', self.provider_login_urls['gmail.com']
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

    def save_result(self, result: EmailVerificationResult):
        """Save verification result to the appropriate CSV file."""
        file_path = self.csv_files[result.category]
        
        # Convert details to string if present
        details_str = str(result.details) if result.details else ""
        
        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([result.email, result.provider, result.reason, details_str])
        
        # Also save to the data folder
        settings.add_email_to_data(result.email, result.category)
        
        logger.info(f"Saved {result.email} to {result.category} list")

    def verify_smtp(self, email: str, mx_servers: List[str], 
                   sender_email: str = "verify@example.com", 
                   timeout: int = 10) -> Dict:
        """
        Verify email existence by connecting to the SMTP server.
        
        This uses the SMTP RCPT TO command to check if the email exists
        without actually sending an email.
        """
        result = {
            "is_deliverable": False,
            "smtp_check": False,
            "reason": None,
            "mx_used": None
        }
        
        if not mx_servers:
            result["reason"] = "No MX records found"
            return result
        
        for mx in mx_servers:
            try:
                with smtplib.SMTP(mx, timeout=timeout) as smtp:
                    smtp.ehlo()
                    # Try to use STARTTLS if available
                    if smtp.has_extn('STARTTLS'):
                        smtp.starttls()
                        smtp.ehlo()
                    
                    # Some servers require a sender address
                    smtp.mail(sender_email)
                    
                    # The key check - see if the recipient is accepted
                    code, message = smtp.rcpt(email)
                    
                    smtp.quit()
                    
                    result["mx_used"] = mx
                    
                    # SMTP status codes:
                    # 250 = Success
                    # 550 = Mailbox unavailable
                    # 551, 552, 553, 450, 451, 452 = Various temporary issues
                    # 503, 550, 551, 553 = Various permanent failures
                    
                    if code == 250:
                        result["is_deliverable"] = True
                        result["smtp_check"] = True
                        return result
                    elif code == 550:
                        # Mark as risky instead of invalid for "Mailbox unavailable"
                        result["reason"] = "Mailbox unavailable" 
                        return result
                    else:
                        result["reason"] = f"SMTP Error: {code} - {message.decode('utf-8', errors='ignore')}"
                        # Continue to next MX if this one gave a temporary error
            
            except (socket.timeout, socket.error, smtplib.SMTPException) as e:
                logger.debug(f"SMTP error with {mx}: {str(e)}")
                # Continue to next MX server
        
        if not result["reason"]:
            result["reason"] = "All MX servers rejected connection or verification"
        return result

    def check_catch_all(self, domain: str) -> bool:
        """
        Check if a domain has a catch-all email configuration.
        Returns True if it's a catch-all domain, False otherwise.
        """
        if not settings.is_enabled("catch_all_detection"):
            return False
            
        # Generate a random email that almost certainly doesn't exist
        random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))
        test_email = f"{random_str}@{domain}"
        
        # Get MX records
        mx_records = self.get_mx_records(domain)
        if not mx_records:
            return False
        
        # Try to verify the random email
        result = self.verify_smtp(test_email, mx_records)
        
        # If the random email is deliverable, it's likely a catch-all domain
        return result.get("is_deliverable", False)

    def verify_email_smtp(self, email: str) -> EmailVerificationResult:
        """
        Verify email using SMTP method.
        """
        # Extract domain
        _, domain = email.split('@')
        
        # Get MX records
        mx_records = self.get_mx_records(domain)
        if not mx_records:
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Domain has no mail servers",
                provider=domain
            )
        
        # Check if it's a catch-all domain
        is_catch_all = self.check_catch_all(domain)
        
        # Verify using SMTP
        smtp_result = self.verify_smtp(email, mx_records)
        
        if smtp_result["is_deliverable"]:
            if is_catch_all:
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Domain has catch-all configuration",
                    provider=domain,
                    details={"smtp_result": smtp_result, "is_catch_all": True}
                )
            else:
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason="Email verified via SMTP",
                    provider=domain,
                    details=smtp_result
                )
        elif smtp_result["reason"] == "Mailbox unavailable":
            # Changed from INVALID to RISKY as per requirements
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason="Mailbox unavailable (may not indicate invalid email)",
                provider=domain,
                details=smtp_result
            )
        else:
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason=f"Email verification failed: {smtp_result['reason']}",
                provider=domain,
                details=smtp_result
            )

    def verify_microsoft_api(self, email: str) -> Optional[EmailVerificationResult]:
        """
        Verify Microsoft email using the GetCredentialType API.
        Returns None if the API is not enabled or if the result is not definitive.
        """
        if not settings.is_enabled("microsoft_api"):
            return None
            
        try:
            # Set up a session with proxy if enabled
            session = requests.Session()
            if settings.is_enabled("proxy_enabled"):
                proxies = settings.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    session.proxies = {
                        "http": proxy,
                        "https": proxy
                    }
            
            # Set headers to look like a browser
            headers = {
                'User-Agent': self.get_random_user_agent(),
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
            
            # Make the request
            response = session.post(
                'https://login.microsoftonline.com/common/GetCredentialType',
                headers=headers,
                json=payload
            )
            
            # Check if the response indicates the email exists
            if response.status_code == 200:
                data = response.json()
                
                # Check for specific indicators in the response
                if 'IfExistsResult' in data:
                    if data['IfExistsResult'] == 0:
                        # 0 indicates the email exists
                        return EmailVerificationResult(
                            email=email,
                            category=VALID,
                            reason="Email address exists (Microsoft API)",
                            provider="Microsoft",
                            details={"response": data}
                        )
                    elif data['IfExistsResult'] == 1:
                        # 1 indicates the email doesn't exist
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason="Email address does not exist (Microsoft API)",
                            provider="Microsoft",
                            details={"response": data}
                        )
                
                # If ThrottleStatus is in the response, the account might exist
                if 'ThrottleStatus' in data and data['ThrottleStatus'] == 1:
                    # Not definitive, return None to fall back to other methods
                    return None
            
            # If we can't determine from the response, return None to fall back to other methods
            return None
        
        except Exception as e:
            logger.error(f"Error verifying Microsoft email via API {email}: {e}")
            return None

    def should_use_smtp(self, email: str) -> bool:
        """
        Determine if SMTP verification should be used for this email.
        Currently only used for Gmail addresses.
        """
        _, domain = email.split('@')
        return domain.lower() == 'gmail.com'

    def is_catch_all_domain(self, domain: str) -> bool:
        """
        Check if a domain is a catch-all domain by testing with a fake email.
        """
        # Generate a random email that almost certainly doesn't exist
        random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))
        test_email = f"{random_str}@{domain}"
        
        # Get MX records
        mx_records = self.get_mx_records(domain)
        if not mx_records:
            return False
        
        # Try to verify the random email
        result = self.verify_smtp(test_email, mx_records)
        
        # If the random email is deliverable, it's likely a catch-all domain
        return result.get("is_deliverable", False)

    def verify_email(self, email: str) -> EmailVerificationResult:
        """
        Verify if an email exists by checking MX records and attempting to log in.
        """
        # Check if email exists in data files first
        exists, category = settings.check_email_in_data(email)
        if exists:
            logger.info(f"Email {email} found in {category} list")
            return EmailVerificationResult(
                email=email,
                category=category,
                reason=f"Email found in {category} list",
                provider="cached"
            )
        
        # Check cache next
        if email in self.result_cache:
            return self.result_cache[email]
        
        # Step 1: Validate email format
        if not self.validate_format(email):
            result = EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Invalid email format",
                provider="unknown"
            )
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Extract domain
        _, domain = email.split('@')
        
        # Check if domain is blacklisted
        if domain in settings.get_blacklisted_domains():
            result = EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Domain is blacklisted",
                provider=domain
            )
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Check if domain should be skipped (whitelisted)
        if domain in self.skip_domains:
            result = EmailVerificationResult(
                email=email,
                category=VALID,
                reason="Domain in whitelist",
                provider=domain
            )
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Step 2: Check MX records
        mx_records = self.get_mx_records(domain)
        
        if not mx_records:
            result = EmailVerificationResult(
                email=email,
                category=INVALID,
                reason="Domain has no mail servers",
                provider="unknown"
            )
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Step 3: Identify the provider
        provider, login_url = self.identify_provider(email)
        
        # Step 4: For Microsoft emails, try API verification first
        if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
            # Check if it's a catch-all domain first
            is_catch_all = self.is_catch_all_domain(domain)
            if is_catch_all:
                # If it's a catch-all domain, switch to Selenium login method
                logger.info(f"Domain {domain} is a catch-all domain, using Selenium login method")
            else:
                # Try API verification
                api_result = self.verify_microsoft_api(email)
                if api_result and api_result.category in [VALID, INVALID]:
                    # Only use API result if it's definitive (valid or invalid)
                    self.result_cache[email] = api_result
                    self.save_result(api_result)
                    return api_result
        
        # Step 5: For Gmail addresses, use SMTP verification
        if self.should_use_smtp(email):
            result = self.verify_email_smtp(email)
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Step 6: For custom domains without a known login URL, use SMTP verification
        if provider == 'custom' or not login_url:
            # Check if it's a catch-all domain
            is_catch_all = self.check_catch_all(domain)
            
            # Verify using SMTP
            smtp_result = self.verify_smtp(email, mx_records)
            
            if smtp_result["is_deliverable"]:
                if is_catch_all:
                    result = EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason="Domain has catch-all configuration",
                        provider="Custom",
                        details={"smtp_result": smtp_result, "is_catch_all": True, "mx_records": mx_records}
                    )
                else:
                    result = EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason="Email verified via SMTP",
                        provider="Custom",
                        details={"smtp_result": smtp_result, "mx_records": mx_records}
                    )
            else:
                result = EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason=f"Email verification failed: {smtp_result['reason']}",
                    provider="Custom",
                    details={"smtp_result": smtp_result, "mx_records": mx_records}
                )
            
            self.result_cache[email] = result
            self.save_result(result)
            return result
        
        # Step 7: Attempt login verification with verification loop if enabled
        if self.verification_loop_enabled:
            # Try with different browsers if the result is not clear
            browsers = settings.get_browsers()
            
            for browser in browsers:
                result = self._verify_login(email, provider, login_url, browser)
                
                # If the result is definitive (valid or invalid), return it
                if result.category in [VALID, INVALID]:
                    self.result_cache[email] = result
                    self.save_result(result)
                    return result
                
                # If we've tried all browsers and still not sure, try SMTP
                if browser == browsers[-1] and result.category in [RISKY, CUSTOM]:
                    logger.info(f"Login verification inconclusive for {email}, trying SMTP")
                    smtp_result = self.verify_email_smtp(email)
                    
                    # If SMTP gives a definitive result, use it
                    if smtp_result.category in [VALID, INVALID]:
                        self.result_cache[email] = smtp_result
                        self.save_result(smtp_result)
                        return smtp_result
                    
                    # If still not definitive, mark as risky
                    self.result_cache[email] = result
                    self.save_result(result)
                    return result
        else:
            # Without verification loop, just try once with the default browser
            result = self._verify_login(email, provider, login_url, "chrome")
            self.result_cache[email] = result
            self.save_result(result)
            return result

    def take_screenshot(self, driver, email, stage):
        """Take a screenshot at a specific stage of the verification process."""
        try:
            filename = f"{SCREENSHOTS_DIR}/{email.replace('@', '_at_')}_{stage}.png"
            driver.save_screenshot(filename)
            logger.info(f"Screenshot saved: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            return None

    def human_like_typing(self, element, text):
        """Type text in a human-like manner with random delays between keystrokes."""
        for char in text:
            element.send_keys(char)
            # Random delay between keystrokes (50-200ms)
            time.sleep(random.uniform(0.05, 0.2))

    def human_like_move_and_click(self, driver, element):
        """Move to an element and click it in a human-like manner."""
        try:
            # Create action chain
            actions = ActionChains(driver)
            
            # Move to a random position first
            viewport_width = driver.execute_script("return window.innerWidth;")
            viewport_height = driver.execute_script("return window.innerHeight;")
            random_x = random.randint(0, viewport_width)
            random_y = random.randint(0, viewport_height)
            
            # Move to random position, then to element with a slight offset, then click
            actions.move_by_offset(random_x, random_y)
            actions.pause(random.uniform(0.1, 0.3))
            
            # Get element location
            element_x = element.location['x']
            element_y = element.location['y']
            
            # Calculate center of element
            element_width = element.size['width']
            element_height = element.size['height']
            center_x = element_x + element_width / 2
            center_y = element_y + element_height / 2
            
            # Move to element with slight random offset
            offset_x = random.uniform(-5, 5)
            offset_y = random.uniform(-5, 5)
            actions.move_to_element_with_offset(element, offset_x, offset_y)
            actions.pause(random.uniform(0.1, 0.3))
            
            # Click
            actions.click()
            actions.perform()
            
            return True
        except Exception as e:
            logger.warning(f"Human-like click failed: {e}")
            # Fall back to regular click
            try:
                element.click()
                return True
            except Exception as click_e:
                logger.error(f"Regular click also failed: {click_e}")
                # Last resort: JavaScript click
                try:
                    driver.execute_script("arguments[0].click();", element)
                    return True
                except Exception as js_e:
                    logger.error(f"JavaScript click failed: {js_e}")
                    return False

    def find_next_button(self, driver):
        """
        Find the 'Next' button using multiple strategies.
        Returns the button element if found, None otherwise.
        """
        # Strategy 1: Look for buttons with specific text
        for text in self.next_button_texts:
            try:
                # Try exact text match
                elements = driver.find_elements(By.XPATH, f"//button[contains(text(), '{text}')]")
                if elements:
                    return elements[0]
                
                # Try case-insensitive match
                elements = driver.find_elements(By.XPATH, f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]")
                if elements:
                    return elements[0]
                
                # Try with span inside button
                elements = driver.find_elements(By.XPATH, f"//button//span[contains(text(), '{text}')]/..")
                if elements:
                    return elements[0]
                
                # Try with input buttons
                elements = driver.find_elements(By.XPATH, f"//input[@type='submit' and contains(@value, '{text}')]")
                if elements:
                    return elements[0]
            except Exception:
                continue
        
        # Strategy 2: Look for common button IDs and classes
        for selector in [
            "#identifierNext",  # Google
            "#idSIButton9",     # Microsoft
            "#login-signin",    # Yahoo
            "button[type='submit']",
            "input[type='submit']",
            ".VfPpkd-LgbsSe-OWXEXe-k8QpJ",  # Google's Next button class
            ".win-button.button_primary"     # Microsoft's Next button class
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        
        # Strategy 3: Look for any button or input that might be a submit button
        try:
            # Look for buttons with common attributes
            for attr in ["submit", "login", "next", "continue", "signin"]:
                elements = driver.find_elements(By.CSS_SELECTOR, f"button[id*='{attr}'], button[class*='{attr}'], button[name*='{attr}']")
                if elements:
                    return elements[0]
            
            # Look for any button as a last resort
            elements = driver.find_elements(By.TAG_NAME, "button")
            if elements:
                # Try to find a button that looks like a submit button (e.g., positioned at the bottom)
                for element in elements:
                    if element.is_displayed() and element.is_enabled():
                        return element
        except Exception:
            pass
        
        return None

    def find_email_field(self, driver):
        """
        Find the email input field using multiple strategies.
        Returns the field element if found, None otherwise.
        """
        # Try common selectors for email fields
        for selector in [
            "input[type='email']", 
            "input[name='email']", 
            "input[name='username']", 
            "input[id*='email']", 
            "input[id*='user']",
            "input[id='identifierId']",  # Google
            "input[name='loginfmt']",    # Microsoft
            "input[id='login-username']" # Yahoo
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and elements[0].is_displayed():
                    return elements[0]
            except Exception:
                continue
        
        # Try to find any input field that might accept email
        try:
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for input_field in inputs:
                try:
                    if input_field.is_displayed() and input_field.get_attribute("type") in ["text", "email"]:
                        return input_field
                except StaleElementReferenceException:
                    continue
        except Exception:
            pass
        
        return None

    def check_for_error_message(self, driver, provider):
        """
        Check if the page contains an error message indicating the email doesn't exist.
        Returns True if an error is found, False otherwise.
        """
        # Check for Google-specific error message first
        if provider == 'gmail.com':
            try:
                error_div = driver.find_element(By.CSS_SELECTOR, 'div.dMNVAe[jsname="OZNMeb"][aria-live="assertive"]')
                if error_div and error_div.is_displayed():
                    error_text = error_div.text.strip()
                    if error_text and ("couldn't find" in error_text.lower() or 
                                     "try again with that email" in error_text.lower()):
                        return True, "Google account not found"
            except Exception:
                pass
        
        # Check for Yahoo-specific error message
        if provider == 'yahoo.com':
            try:
                error_div = driver.find_element(By.CSS_SELECTOR, 'p#username-error.error-msg')
                if error_div and error_div.is_displayed():
                    error_text = error_div.text.strip()
                    if "ne reconnaissons pas cette adresse mail" in error_text:
                        return True, "Yahoo account not found"
            except Exception:
                pass
        
        page_source = driver.page_source.lower()
        
        # Get provider-specific error phrases
        error_phrases = self.nonexistent_email_phrases.get(provider, []) + self.nonexistent_email_phrases['generic']
        
        # Check for each phrase
        for phrase in error_phrases:
            if phrase.lower() in page_source:
                return True, phrase
        
        # Check for specific error elements
        try:
            # Google error message
            google_error = driver.find_elements(By.XPATH, "//div[contains(@class, 'Ekjuhf') or contains(@class, 'o6cuMc')]")
            if google_error and any("couldn't find" in element.text.lower() for element in google_error if element.is_displayed()):
                return True, "Google account not found"
            
            # Microsoft error message
            microsoft_error = driver.find_elements(By.ID, "usernameError")
            if microsoft_error and any(element.is_displayed() for element in microsoft_error):
                return True, "Microsoft account not found"
        except Exception:
            pass
        
        return False, None

    def check_for_microsoft_multi_account(self, driver):
        """
        Check if the page contains a message indicating the email is used with multiple Microsoft accounts.
        Returns True if such a message is found, False otherwise.
        """
        try:
            # Check for the specific div
            multi_account_div = driver.find_elements(By.ID, "loginDescription")
            
            if multi_account_div:
                for div in multi_account_div:
                    if div.is_displayed():
                        text = div.text.strip()
                        for phrase in self.microsoft_multi_account_phrases:
                            if phrase.lower() in text.lower():
                                return True, text
            
            # Check in the page source as well
            page_source = driver.page_source.lower()
            for phrase in self.microsoft_multi_account_phrases:
                if phrase.lower() in page_source:
                    return True, phrase
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for Microsoft multi-account: {e}")
            return False, None

    def get_page_heading(self, driver):
        """Get the main heading of the page."""
        try:
            # Try common heading elements
            for selector in [
                "h1#headingText", # Google
                "div#loginHeader", # Microsoft
                "h1", 
                ".heading", 
                "[role='heading']"
            ]:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.is_displayed() and element.text.strip():
                        return element.text.strip()
            
            return None
        except Exception:
            return None

    def check_for_password_field(self, driver, provider, before_heading=None):
        """
        Check if the page contains a visible password field, indicating the email exists.
        This improved version checks for hidden password fields, page heading changes,
        and URL changes for Google login.
        """
        # Check for URL changes that indicate a valid email (Google specific)
        if provider in ['gmail.com', 'googlemail.com']:
            current_url = driver.current_url
            # Check if URL changed to the password challenge URL
            if '/signin/challenge/pwd' in current_url:
                return True, "URL changed to password challenge"
        
        # Check 
                return True, "URL changed to password challenge"
        
        # Check for heading changes that indicate a valid email
        if provider in self.valid_email_indicators and before_heading:
            after_heading = self.get_page_heading(driver)
            if after_heading:
                # Check if heading changed from sign-in to password/welcome
                if (before_heading.lower() in [h.lower() for h in self.valid_email_indicators[provider]['heading_changes']['before']] and
                    after_heading.lower() in [h.lower() for h in self.valid_email_indicators[provider]['heading_changes']['after']]):
                    return True, "Heading changed to password prompt"
        
        # Check for visible password fields
        try:
            # Find all password fields
            password_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            
            # Check if any password field is visible and not hidden
            for field in password_fields:
                try:
                    # Check if the field is displayed
                    if not field.is_displayed():
                        continue
                    
                    # Check for attributes that indicate a hidden field
                    aria_hidden = field.get_attribute("aria-hidden")
                    tabindex = field.get_attribute("tabindex")
                    class_name = field.get_attribute("class")
                    
                    # Skip fields that are explicitly hidden
                    if (aria_hidden == "true" or 
                        tabindex == "-1" or 
                        any(hidden_class in (class_name or "") for hidden_class in ["moveOffScreen", "Hvu6D", "hidden"])):
                        continue
                    
                    # This is a visible password field
                    return True, "Visible password field found"
                except StaleElementReferenceException:
                    continue
            
            # Check for password-related labels or text that indicate a password prompt
            password_labels = driver.find_elements(By.XPATH, "//label[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'password')]")
            if password_labels and any(label.is_displayed() for label in password_labels):
                return True, "Password label found"
            
            # For Microsoft specifically, check for the password form
            if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                password_form = driver.find_elements(By.CSS_SELECTOR, "form[name='f1'][data-testid='passwordForm']")
                if password_form:
                    return True, "Password form found"
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for password field: {e}")
            return False, None

    def check_for_captcha(self, driver):
        """
        Check if the page contains a CAPTCHA challenge.
        Returns True if a CAPTCHA is found, False otherwise.
        """
        try:
            # Check for CAPTCHA image
            captcha_img = driver.find_elements(By.ID, "captchaimg")
            if captcha_img and any(img.is_displayed() for img in captcha_img):
                return True, "CAPTCHA image found"
            
            # Check for reCAPTCHA
            recaptcha = driver.find_elements(By.CSS_SELECTOR, ".g-recaptcha, iframe[src*='recaptcha']")
            if recaptcha and any(elem.is_displayed() for elem in recaptcha):
                return True, "reCAPTCHA found"
            
            # Check for CAPTCHA in URL
            if '/challenge/ipp' in driver.current_url or 'captcha' in driver.current_url.lower():
                return True, "CAPTCHA challenge in URL"
            
            # Check for CAPTCHA text input
            captcha_input = driver.find_elements(By.CSS_SELECTOR, "input[name='ca'], input[id='ca']")
            if captcha_input and any(input_field.is_displayed() for input_field in captcha_input):
                return True, "CAPTCHA input field found"
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for CAPTCHA: {e}")
            return False, None

    def analyze_google_url(self, url, page_source=None):
        """
        Analyze Google URL to determine the state of the login process.
        Returns a tuple of (state, details)
        """
        # Check for different URL patterns
        if self.google_url_patterns['pwd_challenge'] in url:
            return "valid", "URL indicates password challenge (valid email)"
        elif self.google_url_patterns['rejected'] in url:
            # Rejected URL doesn't necessarily mean invalid email
            # It could be a security measure or rate limiting
            return "rejected", "URL indicates rejected login attempt (security measure)"
        elif self.google_url_patterns['captcha'] in url or 'captcha' in url.lower():
            return "captcha", "URL indicates CAPTCHA challenge"
        elif self.google_url_patterns['security_challenge'] in url:
            return "security", "URL indicates security challenge"
        elif self.google_url_patterns['identifier'] in url:
            # Check if we're still on the identifier page but with an error message
            if page_source and any(phrase.lower() in page_source.lower() for phrase in self.nonexistent_email_phrases['gmail.com']):
                return "invalid", "Error message indicates invalid email"
            return "initial", "Still on identifier page"
        else:
            return "unknown", f"Unknown URL pattern: {url}"

    def _verify_google_email(self, driver, email, initial_url, before_heading):
        """
        Special verification method for Google emails.
        """
        # Get the current URL after clicking next
        current_url = driver.current_url
        logger.info(f"URL after clicking next: {current_url}")
        
        # Take screenshot after clicking next
        self.take_screenshot(driver, email, "after_next")
        
        # Check for CAPTCHA first
        has_captcha, captcha_reason = self.check_for_captcha(driver)
        if has_captcha:
            logger.warning(f"CAPTCHA detected for {email}: {captcha_reason}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"CAPTCHA challenge encountered: {captcha_reason}",
                provider="gmail.com",
                details={"current_url": current_url}
            )
        
        # Get page source for error checking
        page_source = driver.page_source
        
        # Check for error message first
        has_error, error_phrase = self.check_for_error_message(driver, "gmail.com")
        if has_error:
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason=f"Email address does not exist ({error_phrase})",
                provider="gmail.com",
                details={"error_phrase": error_phrase, "current_url": current_url}
            )
        
        # Analyze Google URL to determine state
        state, details = self.analyze_google_url(current_url, page_source)
        logger.info(f"Google URL analysis: {state} - {details}")
        
        if state == "valid":
            return EmailVerificationResult(
                email=email,
                category=VALID,
                reason=f"Email address exists ({details})",
                provider="gmail.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )
        elif state == "invalid":
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason=f"Email address does not exist ({details})",
                provider="gmail.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )
        elif state == "rejected":
            # For rejected URLs, we need to check if there's an error message
            # indicating the email doesn't exist
            has_error, error_phrase = self.check_for_error_message(driver, "gmail.com")
            if has_error:
                return EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason=f"Email address does not exist ({error_phrase})",
                    provider="gmail.com",
                    details={"error_phrase": error_phrase, "current_url": current_url}
                )
            
            # If no clear error message, check for password field
            has_password, password_reason = self.check_for_password_field(driver, "gmail.com", before_heading)
            if has_password:
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason=f"Email address exists ({password_reason})",
                    provider="gmail.com",
                    details={"current_url": current_url}
                )
            
            # If we can't determine, mark as risky
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Rejected login but could not determine if email exists",
                provider="gmail.com",
                details={"current_url": current_url}
            )
        elif state == "captcha":
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"CAPTCHA challenge encountered ({details})",
                provider="gmail.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )
        elif state == "security":
            # If we hit a security challenge, the email likely exists
            return EmailVerificationResult(
                email=email,
                category=VALID,
                reason=f"Email likely exists (security challenge)",
                provider="gmail.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )
        elif state == "initial":
            # Still on the identifier page, check for error messages
            has_error, error_phrase = self.check_for_error_message(driver, "gmail.com")
            if has_error:
                return EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason=f"Email address does not exist ({error_phrase})",
                    provider="gmail.com",
                    details={"error_phrase": error_phrase}
                )
            else:
                # No error message but still on identifier page - might be a UI issue
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Could not proceed past identifier page (no error message)",
                    provider="gmail.com",
                    details={"current_url": current_url}
                )
        else:  # Unknown state
            # Check if we can find a password field anyway
            has_password, password_reason = self.check_for_password_field(driver, "gmail.com", before_heading)
            if has_password:
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason=f"Email address exists ({password_reason})",
                    provider="gmail.com",
                    details={"initial_url": initial_url, "current_url": current_url}
                )
            
            # Check for error messages
            has_error, error_phrase = self.check_for_error_message(driver, "gmail.com")
            if has_error:
                return EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason=f"Email address does not exist ({error_phrase})",
                    provider="gmail.com",
                    details={"error_phrase": error_phrase}
                )
            
            # If we can't determine, mark as risky
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Unknown Google login state: {details}",
                provider="gmail.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )

    def _verify_yahoo_email(self, driver, email, initial_url, before_heading):
        """
        Special verification method for Yahoo emails.
        """
        # Get the current URL after clicking next
        current_url = driver.current_url
        logger.info(f"URL after clicking next: {current_url}")
        
        # Take screenshot after clicking next
        self.take_screenshot(driver, email, "after_yahoo_next")
        
        # Check for error message first
        has_error, error_phrase = self.check_for_error_message(driver, "yahoo.com")
        if has_error:
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason=f"Email address does not exist ({error_phrase})",
                provider="yahoo.com",
                details={"error_phrase": error_phrase, "current_url": current_url}
            )
        
        # Check if URL changed to challenge URL (indicates valid email)
        if "account/challenge" in current_url:
            return EmailVerificationResult(
                email=email,
                category=VALID,
                reason="Email address exists (redirected to challenge page)",
                provider="yahoo.com",
                details={"initial_url": initial_url, "current_url": current_url}
            )
        
        # Check for password field
        has_password, password_reason = self.check_for_password_field(driver, "yahoo.com", before_heading)
        if has_password:
            return EmailVerificationResult(
                email=email,
                category=VALID,
                reason=f"Email address exists ({password_reason})",
                provider="yahoo.com",
                details={"current_url": current_url}
            )
        
        # If we can't determine, mark as risky
        return EmailVerificationResult(
            email=email,
            category=RISKY,
            reason="Could not determine if Yahoo email exists",
            provider="yahoo.com",
            details={"initial_url": initial_url, "current_url": current_url}
        )

    def _get_browser_driver(self, browser_type):
        """
        Get a WebDriver instance for the specified browser type.
        """
        browser_type = browser_type.lower()
        
        if browser_type == "chrome":
            # Get a random user agent if rotation is enabled
            if settings.is_enabled("user_agent_rotation"):
                self.chrome_options.add_argument(f"--user-agent={self.get_random_user_agent()}")
            
            # Add proxy if enabled
            if settings.is_enabled("proxy_enabled"):
                proxies = settings.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    self.chrome_options.add_argument(f'--proxy-server={proxy}')
            
            return webdriver.Chrome(options=self.chrome_options)
        
        elif browser_type == "edge":
            # Get a random user agent if rotation is enabled
            if settings.is_enabled("user_agent_rotation"):
                self.edge_options.add_argument(f"--user-agent={self.get_random_user_agent()}")
            
            # Add proxy if enabled
            if settings.is_enabled("proxy_enabled"):
                proxies = settings.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    self.edge_options.add_argument(f'--proxy-server={proxy}')
            
            return webdriver.Edge(options=self.edge_options)
        
        elif browser_type == "firefox":
            # Get a random user agent if rotation is enabled
            if settings.is_enabled("user_agent_rotation"):
                self.firefox_options.set_preference("general.useragent.override", self.get_random_user_agent())
            
            # Add proxy if enabled
            if settings.is_enabled("proxy_enabled"):
                proxies = settings.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    proxy_parts = proxy.split(":")
                    if len(proxy_parts) == 2:
                        host, port = proxy_parts
                        self.firefox_options.set_preference("network.proxy.type", 1)
                        self.firefox_options.set_preference("network.proxy.http", host)
                        self.firefox_options.set_preference("network.proxy.http_port", int(port))
                        self.firefox_options.set_preference("network.proxy.ssl", host)
                        self.firefox_options.set_preference("network.proxy.ssl_port", int(port))
            
            return webdriver.Firefox(options=self.firefox_options)
        
        else:
            # Default to Chrome
            logger.warning(f"Unknown browser type: {browser_type}, defaulting to Chrome")
            return webdriver.Chrome(options=self.chrome_options)

    def _verify_login(self, email: str, provider: str, login_url: str, browser_type: str = "chrome") -> EmailVerificationResult:
        """
        Verify email by attempting to log in and analyzing the response.
        """
        driver = None
        try:
            # Initialize the browser
            driver = self._get_browser_driver(browser_type)
            driver.command_executor._commands["get"] = ("POST", '/session/$sessionId/url')
            
            # Navigate to login page
            logger.info(f"Navigating to login page: {login_url} using {browser_type}")
            driver.execute('get', {'url': login_url})
            
            # Wait for page to load with random delay (2-4 seconds)
            time.sleep(random.uniform(2, 4))
            
            # Store the initial URL for comparison later
            initial_url = driver.current_url
            logger.info(f"Initial URL: {initial_url}")
            
            # Get the initial page heading
            before_heading = self.get_page_heading(driver)
            logger.info(f"Initial page heading: {before_heading}")
            
            # Take screenshot before entering email
            self.take_screenshot(driver, email, f"before_email_{browser_type}")
            
            # Find email input field
            email_field = self.find_email_field(driver)
            
            if not email_field:
                logger.warning(f"Could not find email input field for {email}")
                # If we can't find the email field, it might be a custom login page
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Could not find email input field on login page",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Enter email with human-like typing
            logger.info(f"Entering email: {email}")
            self.human_like_typing(email_field, email)
            
            # Random delay after typing (0.5-1.5 seconds)
            time.sleep(random.uniform(0.5, 1.5))
            
            # Find next button
            next_button = self.find_next_button(driver)
            
            if not next_button:
                logger.warning(f"Could not find next button for {email}")
                # If we can't find the next button, it might be a custom login page
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Could not find next/submit button on login page",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Take screenshot before clicking next
            self.take_screenshot(driver, email, f"before_next_{browser_type}")
            
            # Try to click next button with human-like movement
            logger.info("Clicking next button")
            click_success = self.human_like_move_and_click(driver, next_button)
            
            if not click_success:
                logger.error("All click methods failed")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Could not click next button after multiple attempts",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Wait for response with configurable delay
            wait_time = settings.get_browser_wait_time()
            time.sleep(wait_time)
            
            # Special handling for Google emails
            if provider in ['gmail.com', 'googlemail.com']:
                return self._verify_google_email(driver, email, initial_url, before_heading)
            
            # Special handling for Yahoo emails
            if provider == 'yahoo.com':
                return self._verify_yahoo_email(driver, email, initial_url, before_heading)
            
            # For Microsoft providers, check for multi-account message
            if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                has_multi_account, multi_account_text = self.check_for_microsoft_multi_account(driver)
                if has_multi_account:
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason="Could not determine if email exists (multiple Microsoft accounts)",
                        provider=provider,
                        details={"multi_account_text": multi_account_text, "browser": browser_type}
                    )
            
            # For non-Google providers, continue with the original logic
            # Check for error messages first
            has_error, error_phrase = self.check_for_error_message(driver, provider)
            if has_error:
                return EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason="Email address does not exist",
                    provider=provider,
                    details={"error_phrase": error_phrase, "browser": browser_type}
                )
            
            # Check for password field or heading changes
            has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
            if has_password:
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason=f"Email address exists ({password_reason})",
                    provider=provider,
                    details={"browser": browser_type}
                )
            
            # Check if we were redirected to a custom domain login
            original_domain = login_url.split('/')[2]
            current_domain = driver.current_url.split('/')[2]
            
            # If we're redirected to a different domain, it might be a custom login
            if original_domain != current_domain and "login" in driver.current_url.lower():
                # Try to find password field on the new page
                has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                if has_password:
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email address exists ({password_reason} after redirect)",
                        provider=provider,
                        details={"redirect_url": driver.current_url, "browser": browser_type}
                    )
                
                # If we can't determine, mark as custom
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Redirected to custom login page",
                    provider=provider,
                    details={"redirect_url": driver.current_url, "browser": browser_type}
                )
            
            # If we can't find a password field or error message, check if we're still on the same page
            if login_url.split('?')[0] in driver.current_url.split('?')[0]:
                # We're still on the login page, but no clear error message
                # This is risky - might exist but we can't confirm
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Could not determine if email exists (no password prompt or error)",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            else:
                # We were redirected somewhere else
                # Try one more time to check for password field
                has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                if has_password:
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email address exists ({password_reason} after redirect)",
                        provider=provider,
                        details={"redirect_url": driver.current_url, "browser": browser_type}
                    )
                
                # If still no password field, mark as custom
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Redirected to another page",
                    provider=provider,
                    details={"redirect_url": driver.current_url, "browser": browser_type}
                )
        
        except WebDriverException as e:
            logger.error(f"Browser error verifying {email}: {e}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Browser error: {str(e)}",
                provider=provider,
                details={"browser": browser_type}
            )
        
        except Exception as e:
            logger.error(f"Error verifying {email}: {e}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Verification error: {str(e)}",
                provider=provider,
                details={"browser": browser_type}
            )
        
        finally:
            # Don't close the browser until verification is complete
            if driver:
                driver.quit()

    def _terminal_worker(self, terminal_id):
        """
        Worker function for multi-terminal support.
        """
        logger.info(f"Terminal {terminal_id} started")
        
        while True:
            try:
                # Get an email from the queue
                email = self.email_queue.get(block=False)
                
                # Verify the email
                logger.info(f"Terminal {terminal_id} verifying {email}")
                result = self.verify_email(email)
                
                # Put the result in the result queue
                self.result_queue.put((email, result))
                
                # Mark the task as done
                self.email_queue.task_done()
                
                # Add a delay to avoid rate limiting
                time.sleep(random.uniform(1, 2))
            
            except queue.Empty:
                # No more emails to verify
                logger.info(f"Terminal {terminal_id} finished")
                break
            
            except Exception as e:
                logger.error(f"Terminal {terminal_id} error: {e}")
                # Put the email back in the queue
                self.email_queue.put(email)
                self.email_queue.task_done()
                
                # Add a delay before retrying
                time.sleep(random.uniform(5, 10))

    def batch_verify(self, emails: List[str]) -> Dict[str, EmailVerificationResult]:
        """
        Verify multiple email addresses.
        """
        results = {}
        
        # Check if multi-terminal support is enabled
        if self.multi_terminal_enabled and len(emails) > 1:
            # Put all emails in the queue
            for email in emails:
                self.email_queue.put(email)
            
            # Start terminal threads
            for i in range(min(self.terminal_count, len(emails))):
                thread = threading.Thread(target=self._terminal_worker, args=(i+1,))
                thread.daemon = True
                thread.start()
                self.terminal_threads.append(thread)
            
            # Wait for all emails to be verified
            self.email_queue.join()
            
            # Get results from the result queue
            while not self.result_queue.empty():
                email, result = self.result_queue.get()
                results[email] = result
        else:
            # Single-terminal verification
            for email in emails:
                results[email] = self.verify_email(email)
                # Add a delay between checks to avoid rate limiting
                time.sleep(random.uniform(2, 4))
        
        return results

    def get_results_summary(self) -> Dict[str, int]:
        """Get a summary of verification results."""
        counts = {
            VALID: 0,
            INVALID: 0,
            RISKY: 0,
            CUSTOM: 0
        }
        
        # Count from CSV files
        for category, file_path in self.csv_files.items():
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    # Subtract 1 for the header row
                    counts[category] = sum(1 for _ in f) - 1
        
        return counts

    def get_statistics(self, verification_name=None):
        """
        Get detailed statistics for the verification results.
        If verification_name is provided, get statistics for that verification.
        Otherwise, get global statistics.
        """
        if verification_name:
            return settings.get_verification_statistics(verification_name)
        
        # Get global statistics
        statistics = {
            "valid": {
                "total": 0,
                "reasons": {}
            },
            "invalid": {
                "total": 0,
                "reasons": {}
            },
            "risky": {
                "total": 0,
                "reasons": {}
            },
            "custom": {
                "total": 0,
                "reasons": {}
            },
            "domains": {}
        }
        
        # Process each category
        for category, file_path in self.csv_files.items():
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Skip header
                    
                    for row in reader:
                        if len(row) >= 3:
                            email, provider, reason = row[:3]
                            
                            # Update category total
                            statistics[category]["total"] += 1
                            
                            # Update reason frequency
                            if reason not in statistics[category]["reasons"]:
                                statistics[category]["reasons"][reason] = 0
                            statistics[category]["reasons"][reason] += 1
                            
                            # Update domain statistics
                            _, domain = email.split('@')
                            if domain not in statistics["domains"]:
                                statistics["domains"][domain] = {
                                    "total": 0,
                                    "valid": 0,
                                    "invalid": 0,
                                    "risky": 0,
                                    "custom": 0
                                }
                            
                            statistics["domains"][domain]["total"] += 1
                            statistics["domains"][domain][category] += 1
        
        return statistics

# If this script is run directly, provide a simple CLI
if __name__ == "__main__":
    print("\nEmail Verification Tool (Login Method)")
    print("=====================================\n")
    
    # Initialize verifier with default skip domains
    skip_domains = [
        "example.com",
        "test.com",
        "domain.com",
        "yourdomain.com",
        "mydomain.com"
    ]
    
    verifier = ImprovedLoginVerifier(skip_domains=skip_domains)
    
    while True:
        print("\nOptions:")
        print("1. Verify a single email")
        print("2. Verify multiple emails")
        print("3. Show results summary")
        print("4. Show detailed statistics")
        print("5. Settings")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ")
        
        if choice == "1":
            email = input("\nEnter an email to verify: ")
            print(f"\nVerifying {email}...")
            result = verifier.verify_email(email)
            print(f"\nResult: {result}")
            
        elif choice == "2":
            print("\nBulk Verification:")
            print("1. Load from CSV file")
            print("2. Enter emails manually")
            
            bulk_choice = input("\nEnter your choice (1-2): ")
            
            emails = []
            
            if bulk_choice == "1":
                # Load from CSV
                file_path = input("\nEnter the path to the CSV file: ")
                try:
                    with open(file_path, 'r') as f:
                        for line in f:
                            email = line.strip()
                            if '@' in email:  # Basic validation
                                emails.append(email)
                    
                    if not emails:
                        print("\nNo valid emails found in the file.")
                        continue
                except Exception as e:
                    print(f"\nError reading file: {e}")
                    continue
            
            elif bulk_choice == "2":
                # Enter manually
                emails_input = input("\nEnter emails separated by commas: ")
                emails = [email.strip() for email in emails_input.split(",") if '@' in email.strip()]
                
                if not emails:
                    print("\nNo valid emails provided.")
                    continue
            
            # Ask if multi-terminal should be used
            if len(emails) > 1:
                use_multi = input("\nUse multi-terminal for faster verification? (y/n): ")
                if use_multi.lower() == 'y':
                    verifier.multi_terminal_enabled = True
                    terminal_count = input(f"\nEnter number of terminals to use (1-{min(8, len(emails))}): ")
                    try:
                        verifier.terminal_count = min(int(terminal_count), 8, len(emails))
                    except ValueError:
                        verifier.terminal_count = min(2, len(emails))
                else:
                    verifier.multi_terminal_enabled = False
            
            # Verify emails
            print(f"\nVerifying {len(emails)} emails...")
            results = verifier.batch_verify(emails)
            
            # Print summary
            valid_count = sum(1 for result in results.values() if result.category == VALID)
            invalid_count = sum(1 for result in results.values() if result.category == INVALID)
            risky_count = sum(1 for result in results.values() if result.category == RISKY)
            custom_count = sum(1 for result in results.values() if result.category == CUSTOM)
            
            print("\nVerification Summary:")
            print(f"Valid emails: {valid_count}")
            print(f"Invalid emails: {invalid_count}")
            print(f"Risky emails: {risky_count}")
            print(f"Custom emails: {custom_count}")
            
            # Print detailed results
            print("\nDetailed Results:")
            for email, result in results.items():
                print(f"{email}: {result.category} - {result.reason}")
            
            # Save verification statistics
            save_stats = input("\nDo you want to save these verification statistics? (y/n): ")
            if save_stats.lower() == 'y':
                verification_name = input("\nEnter a name for this verification: ")
                statistics = verifier.get_statistics()
                settings.save_verification_statistics(verification_name, statistics)
                print(f"\nStatistics saved as '{verification_name}'")
        
        elif choice == "3":
            # Show results summary
            summary = verifier.get_results_summary()
            print("\nResults Summary:")
            print(f"Valid emails: {summary[VALID]}")
            print(f"Invalid emails: {summary[INVALID]}")
            print(f"Risky emails: {summary[RISKY]}")
            print(f"Custom emails: {summary[CUSTOM]}")
            print(f"\nTotal: {sum(summary.values())}")
            
            print("\nResults are saved in the following files:")
            for category, file_path in verifier.csv_files.items():
                print(f"{category.capitalize()} emails: {file_path}")
            
            print("\nResults are also saved in the data folder:")
            print("./data/Valid.csv")
            print("./data/Invalid.csv")
            print("./data/Risky.csv")
            print("./data/Custom.csv")
        
        elif choice == "4":
            # Show detailed statistics
            print("\nStatistics Options:")
            print("1. Global statistics")
            print("2. Specific verification statistics")
            
            stats_choice = input("\nEnter your choice (1-2): ")
            
            if stats_choice == "1":
                # Show global statistics
                statistics = verifier.get_statistics()
                
                print("\nGlobal Statistics:")
                print("-" * 50)
                
                print("\nCategory Totals:")
                print(f"Valid emails: {statistics['valid']['total']}")
                print(f"Invalid emails: {statistics['invalid']['total']}")
                print(f"Risky emails: {statistics['risky']['total']}")
                print(f"Custom emails: {statistics['custom']['total']}")
                
                print("\nTop Domains:")
                sorted_domains = sorted(statistics["domains"].items(), 
                                        key=lambda x: x[1]["total"], reverse=True)
                for domain, stats in sorted_domains[:10]:  # Show top 10
                    print(f"{domain}: {stats['total']} total, {stats['valid']} valid, "
                          f"{stats['invalid']} invalid, {stats['risky']} risky, "
                          f"{stats['custom']} custom")
                
                print("\nReason Frequency:")
                for category in ["valid", "invalid", "risky", "custom"]:
                    print(f"\n{category.capitalize()} Reasons:")
                    sorted_reasons = sorted(statistics[category]["reasons"].items(),
                                           key=lambda x: x[1], reverse=True)
                    for reason, count in sorted_reasons[:5]:  # Show top 5
                        print(f"- {reason}: {count}")
            
            elif stats_choice == "2":
                # Show specific verification statistics
                verification_names = settings.get_verification_names()
                
                if not verification_names:
                    print("\nNo saved verification statistics found.")
                    continue
                
                print("\nSaved Verifications:")
                for i, name in enumerate(verification_names, 1):
                    print(f"{i}. {name}")
                
                verification_index = input("\nEnter the number of the verification to view: ")
                try:
                    verification_index = int(verification_index) - 1
                    if 0 <= verification_index < len(verification_names):
                        verification_name = verification_names[verification_index]
                        statistics = settings.get_verification_statistics(verification_name)
                        
                        if not statistics:
                            print(f"\nNo statistics found for '{verification_name}'")
                            continue
                        
                        print(f"\nStatistics for '{verification_name}':")
                        print("-" * 50)
                        
                        print("\nCategory Totals:")
                        print(f"Valid emails: {statistics['valid']['total']}")
                        print(f"Invalid emails: {statistics['invalid']['total']}")
                        print(f"Risky emails: {statistics['risky']['total']}")
                        print(f"Custom emails: {statistics['custom']['total']}")
                        
                        print("\nTop Domains:")
                        sorted_domains = sorted(statistics["domains"].items(), 
                                                key=lambda x: x[1]["total"], reverse=True)
                        for domain, stats in sorted_domains[:10]:  # Show top 10
                            print(f"{domain}: {stats['total']} total, {stats['valid']} valid, "
                                  f"{stats['invalid']} invalid, {stats['risky']} risky, "
                                  f"{stats['custom']} custom")
                        
                        print("\nReason Frequency:")
                        for category in ["valid", "invalid", "risky", "custom"]:
                            print(f"\n{category.capitalize()} Reasons:")
                            sorted_reasons = sorted(statistics[category]["reasons"].items(),
                                                   key=lambda x: x[1], reverse=True)
                            for reason, count in sorted_reasons[:5]:  # Show top 5
                                print(f"- {reason}: {count}")
                    else:
                        print("\nInvalid selection.")
                except ValueError:
                    print("\nInvalid input. Please enter a number.")
        
        elif choice == "5":
            # Settings
            print("\nSettings:")
            print("1. Multi-terminal settings")
            print("2. Browser settings")
            print("3. Domain lists")
            print("4. SMTP accounts")
            print("5. Proxy settings")
            
            settings_choice = input("\nEnter your choice (1-5): ")
            
            if settings_choice == "1":
                # Multi-terminal settings
                print("\nMulti-terminal Settings:")
                current_enabled = settings.is_enabled("multi_terminal_enabled")
                current_count = settings.get("terminal_count", "2")
                
                print(f"Multi-terminal is currently {'enabled' if current_enabled else 'disabled'}")
                print(f"Current terminal count: {current_count}")
                
                enable = input("\nEnable multi-terminal? (y/n): ")
                if enable.lower() == 'y':
                    count = input("Enter number of terminals (1-8): ")
                    try:
                        count = min(max(1, int(count)), 8)
                    except ValueError:
                        count = 2
                    
                    settings.set("multi_terminal_enabled", "True", True)
                    settings.set("terminal_count", str(count), True)
                    print(f"\nMulti-terminal enabled with {count} terminals")
                else:
                    settings.set("multi_terminal_enabled", "False", False)
                    print("\nMulti-terminal disabled")
            
            elif settings_choice == "2":
                # Browser settings
                print("\nBrowser Settings:")
                current_browsers = settings.get("browsers", "chrome")
                current_wait_time = settings.get("browser_wait_time", "3")
                
                print(f"Current browsers: {current_browsers}")
                print(f"Current browser wait time: {current_wait_time} seconds")
                
                browsers = input("\nEnter browsers to use (comma-separated, e.g., chrome,edge,firefox): ")
                if browsers:
                    settings.set("browsers", browsers, True)
                
                wait_time = input("Enter browser wait time in seconds: ")
                try:
                    wait_time = max(1, int(wait_time))
                    settings.set("browser_wait_time", str(wait_time), True)
                except ValueError:
                    pass
                
                print("\nBrowser settings updated")
            
            elif settings_choice == "3":
                # Domain lists
                print("\nDomain Lists:")
                print("1. View blacklisted domains")
                print("2. Add domain to blacklist")
                print("3. View whitelisted domains")
                print("4. Add domain to whitelist")
                
                domain_choice = input("\nEnter your choice (1-4): ")
                
                if domain_choice == "1":
                    # View blacklisted domains
                    blacklisted = settings.get_blacklisted_domains()
                    print("\nBlacklisted Domains:")
                    if blacklisted:
                        for domain in blacklisted:
                            print(f"- {domain}")
                    else:
                        print("No blacklisted domains")
                
                elif domain_choice == "2":
                    # Add domain to blacklist
                    domain = input("\nEnter domain to blacklist: ")
                    if domain:
                        with open("./data/D-blacklist.csv", 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow([domain])
                        print(f"\n{domain} added to blacklist")
                
                elif domain_choice == "3":
                    # View whitelisted domains
                    whitelisted = settings.get_whitelisted_domains()
                    print("\nWhitelisted Domains:")
                    if whitelisted:
                        for domain in whitelisted:
                            print(f"- {domain}")
                    else:
                        print("No whitelisted domains")
                
                elif domain_choice == "4":
                    # Add domain to whitelist
                    domain = input("\nEnter domain to whitelist: ")
                    if domain:
                        with open("./data/D-WhiteList.csv", 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow([domain])
                        print(f"\n{domain} added to whitelist")
            
            elif settings_choice == "4":
                # SMTP accounts
                print("\nSMTP Accounts:")
                accounts = settings.get_smtp_accounts()
                
                if accounts:
                    print(f"\nFound {len(accounts)} SMTP accounts:")
                    for i, account in enumerate(accounts, 1):
                        print(f"{i}. {account['email']} ({account['smtp_server']}:{account['smtp_port']})")
                
                add_account = input("\nAdd a new SMTP account? (y/n): ")
                if add_account.lower() == 'y':
                    smtp_server = input("Enter SMTP server (e.g., smtp.gmail.com): ")
                    smtp_port = input("Enter SMTP port (e.g., 587): ")
                    imap_server = input("Enter IMAP server (e.g., imap.gmail.com): ")
                    imap_port = input("Enter IMAP port (e.g., 993): ")
                    email_address = input("Enter email address: ")
                    password = input("Enter password: ")
                    
                    try:
                        smtp_port = int(smtp_port)
                        imap_port = int(imap_port)
                        
                        settings.add_smtp_account(
                            smtp_server, smtp_port, imap_server, imap_port, email_address, password
                        )
                        print("\nSMTP account added successfully")
                    except ValueError:
                        print("\nInvalid port number")
            
            elif settings_choice == "5":
                # Proxy settings
                print("\nProxy Settings:")
                current_enabled = settings.is_enabled("proxy_enabled")
                current_proxies = settings.get_proxies()
                
                print(f"Proxy is currently {'enabled' if current_enabled else 'disabled'}")
                if current_proxies:
                    print("\nConfigured proxies:")
                    for i, proxy in enumerate(current_proxies, 1):
                        print(f"{i}. {proxy}")
                else:
                    print("No proxies configured")
                
                enable = input("\nEnable proxy? (y/n): ")
                if enable.lower() == 'y':
                    settings.set("proxy_enabled", "True", True)
                    
                    add_proxy = input("Add a new proxy? (y/n): ")
                    if add_proxy.lower() == 'y':
                        proxy = input("Enter proxy (format: host:port): ")
                        if proxy:
                            settings.add_proxy(proxy)
                            print(f"\nProxy {proxy} added")
                else:
                    settings.set("proxy_enabled", "False", False)
                    print("\nProxy disabled")
        
        elif choice == "6":
            # Exit
            print("\nExiting Email Verification Tool. Goodbye!")
            break
        
        else:
            print("\nInvalid choice. Please try again.")