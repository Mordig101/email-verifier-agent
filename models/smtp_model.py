import socket
import smtplib
import logging
import time
import random
from typing import Dict, List, Any, Optional
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class SMTPModel:
    """Model for SMTP-based email verification."""
    
    def __init__(self, settings_model):
        """
        Initialize the SMTP model.
        
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
    
    def verify_smtp(self, email: str, mx_servers: List[str], 
                   sender_email: str = "verify@example.com", 
                   timeout: int = 10) -> Dict[str, Any]:
        """
        Verify email existence by connecting to the SMTP server.
        
        This uses the SMTP RCPT TO command to check if the email exists
        without actually sending an email.
        
        Args:
            email: The email address to verify
            mx_servers: List of MX servers to try
            sender_email: The sender email address to use
            timeout: Connection timeout in seconds
            
        Returns:
            Dict[str, Any]: Result of the verification
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
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
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
                            break
                
                except (socket.timeout, ConnectionRefusedError) as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = 2 ** retry_count  # Exponential backoff
                        logger.warning(f"Network error with {mx}, retrying in {wait_time}s: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Max retries reached for {mx}: {str(e)}")
                        break
                
                except (socket.error, smtplib.SMTPException) as e:
                    logger.debug(f"SMTP error with {mx}: {str(e)}")
                    # Continue to next MX server
                    break
        
        if not result["reason"]:
            result["reason"] = "All MX servers rejected connection or verification"
        return result
    
    def check_catch_all(self, domain: str, mx_records: List[str]) -> bool:
        """
        Check if a domain has a catch-all email configuration.
        
        Args:
            domain: The domain to check
            mx_records: List of MX records for the domain
            
        Returns:
            bool: True if it's a catch-all domain, False otherwise
        """
        if not self.settings_model.is_enabled("catch_all_detection"):
            return False
            
        # Generate a random email that almost certainly doesn't exist
        random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))
        test_email = f"{random_str}@{domain}"
        
        # Try to verify the random email
        result = self.verify_smtp(test_email, mx_records)
        
        # If the random email is deliverable, it's likely a catch-all domain
        return result.get("is_deliverable", False)
    
    def verify_email_smtp(self, email: str, mx_records: List[str]) -> EmailVerificationResult:
        """
        Verify email using SMTP method.
        
        Args:
            email: The email address to verify
            mx_records: List of MX records for the domain
            
        Returns:
            EmailVerificationResult: The verification result
        """
        logger.info(f"SMTP verification started for {email}")
        
        # Extract domain
        _, domain = email.split('@')
        
        # Check rate limiting if rate limiter is set
        if self.rate_limiter and self.rate_limiter.is_rate_limited(domain):
            wait_time = self.rate_limiter.get_backoff_time(domain)
            logger.info(f"SMTP verification rate limited for {domain}, waiting {wait_time}s")
            time.sleep(wait_time)
            
            # Record this request
            self.rate_limiter.add_request(domain)
        
        # Check if it's a catch-all domain
        is_catch_all = self.check_catch_all(domain, mx_records)
        if is_catch_all:
            logger.info(f"SMTP verification detected catch-all domain: {domain}")
        
        # Verify using SMTP
        smtp_result = self.verify_smtp(email, mx_records)
        
        if smtp_result["is_deliverable"]:
            if is_catch_all:
                logger.info(f"SMTP verification result for {email}: RISKY (Domain has catch-all configuration)")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Domain has catch-all configuration",
                    provider=domain,
                    details={"smtp_result": smtp_result, "is_catch_all": True}
                )
            else:
                logger.info(f"SMTP verification result for {email}: VALID (Email verified via SMTP)")
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason="Email verified via SMTP",
                    provider=domain,
                    details=smtp_result
                )
        elif smtp_result["reason"] == "Mailbox unavailable":
            # Changed from INVALID to RISKY as per requirements
            logger.info(f"SMTP verification result for {email}: RISKY (Mailbox unavailable)")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason="Mailbox unavailable (may not indicate invalid email)",
                provider=domain,
                details=smtp_result
            )
        else:
            logger.info(f"SMTP verification result for {email}: INVALID ({smtp_result['reason']})")
            return EmailVerificationResult(
                email=email,
                category=INVALID,
                reason=f"Email verification failed: {smtp_result['reason']}",
                provider=domain,
                details=smtp_result
            )
