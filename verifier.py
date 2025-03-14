import os
import csv
import time
import random
import logging
import argparse
import threading
import queue
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import the verification modules
try:
    from verifier1 import ImprovedLoginVerifier, VALID, INVALID, RISKY, CUSTOM
    from verifier2 import EmailBounceVerifier
except ImportError:
    # For relative imports when running as a package
    from .verifier1 import ImprovedLoginVerifier, VALID, INVALID, RISKY, CUSTOM
    from .verifier2 import EmailBounceVerifier

# Import settings
try:
    from settings.settings import Settings
except ImportError:
    # For relative imports when running as a package
    from .settings.settings import Settings

class UnifiedEmailVerifier:
    def __init__(self, output_dir="./results", skip_domains=None):
        """
        Initialize the unified email verification system.
        
        Args:
            output_dir: Directory to store results
            skip_domains: List of domains to skip verification
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize settings
        self.settings = Settings()
        
        # Initialize skip domains
        self.skip_domains = skip_domains or []
        
        # Add domains from whitelist
        self.skip_domains.extend(self.settings.get_whitelisted_domains())
        
        # Initialize the login verifier
        self.login_verifier = ImprovedLoginVerifier(output_dir=os.path.join(output_dir, "login_verification"), skip_domains=self.skip_domains)
        
        # Email bounce verifier will be initialized when needed with user credentials
        self.bounce_verifier = None
        
        # Statistics tracking
        self.stats = {
            "domains": {},
            "total": {
                VALID: 0,
                INVALID: 0,
                RISKY: 0,
                CUSTOM: 0,
                "total": 0,
                "start_time": None,
                "end_time": None
            }
        }
        
        # Multi-terminal support
        self.multi_terminal_enabled = self.settings.is_enabled("multi_terminal_enabled")
        self.terminal_count = self.settings.get_terminal_count()
        self.email_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.terminal_threads = []
        
        # Verification loop
        self.verification_loop_enabled = self.settings.is_enabled("verification_loop_enabled")
        
        # Ensure data directory structure exists
        self._ensure_data_structure()
    
    def _ensure_data_structure(self):
        """Ensure the data directory structure exists."""
        data_dir = "./data"
        os.makedirs(data_dir, exist_ok=True)
        
        # Create required data files if they don't exist
        data_files = [
            "D-blacklist.csv",
            "D-WhiteList.csv",
            "Valid.csv",
            "Invalid.csv",
            "Risky.csv",
            "Custom.csv"
        ]
        
        for file in data_files:
            file_path = os.path.join(data_dir, file)
            if not os.path.exists(file_path):
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if file in ["D-blacklist.csv", "D-WhiteList.csv"]:
                        writer.writerow(["domain"])
                    else:
                        writer.writerow(["email"])
    
    def set_bounce_verifier(self, smtp_server, smtp_port, imap_server, imap_port, email_address, password):
        """Set up the bounce verifier with user credentials."""
        self.bounce_verifier = EmailBounceVerifier(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            imap_server=imap_server,
            imap_port=imap_port,
            email_address=email_address,
            password=password,
            output_dir=os.path.join(self.output_dir, "bounce_verification")
        )
    
    def should_skip_domain(self, email):
        """Check if the domain should be skipped for verification."""
        _, domain = email.split('@')
        return domain in self.skip_domains
    
    def should_use_smtp(self, email):
        """Determine if SMTP verification should be used for this email."""
        _, domain = email.split('@')
        # Add domains that should use SMTP verification
        smtp_domains = ['gmail.com']
        return domain.lower() in smtp_domains
    
    def verify_email(self, email):
        """
        Verify a single email using the appropriate method.
        
        Args:
            email: Email address to verify
            
        Returns:
            Verification result
        """
        # Pre-verification check: Check if email exists in data files
        exists, category = self.settings.check_email_in_data(email)
        if exists:
            logger.info(f"Email {email} found in {category} list")
            result = {
                "email": email,
                "category": category,
                "reason": f"Email found in {category} list",
                "provider": "cached",
                "method": "cached"
            }
            return result
        
        # Update statistics
        _, domain = email.split('@')
        if domain not in self.stats["domains"]:
            self.stats["domains"][domain] = {
                VALID: 0,
                INVALID: 0,
                RISKY: 0,
                CUSTOM: 0,
                "total": 0
            }
        
        # Check if domain is blacklisted
        if domain in self.settings.get_blacklisted_domains():
            logger.info(f"Domain {domain} is blacklisted")
            result = {
                "email": email,
                "category": INVALID,
                "reason": "Domain is blacklisted",
                "provider": domain,
                "method": "blacklist"
            }
            self.stats["domains"][domain][INVALID] += 1
            self.stats["domains"][domain]["total"] += 1
            self.stats["total"][INVALID] += 1
            self.stats["total"]["total"] += 1
            
            # Save to data folder
            self.settings.add_email_to_data(email, INVALID)
            
            return result
        
        # Check if we should skip this domain (whitelisted)
        if self.should_skip_domain(email):
            logger.info(f"Skipping verification for {email} (domain in whitelist)")
            result = {
                "email": email,
                "category": VALID,  # Assume valid for skipped domains
                "reason": "Domain in whitelist",
                "provider": domain,
                "method": "whitelist"
            }
            self.stats["domains"][domain][VALID] += 1
            self.stats["domains"][domain]["total"] += 1
            self.stats["total"][VALID] += 1
            self.stats["total"]["total"] += 1
            
            # Save to data folder
            self.settings.add_email_to_data(email, VALID)
            
            return result
        
        # Use verification loop if enabled
        if self.verification_loop_enabled:
            # Try with different methods until we get a clear result
            # 1. First try login verification
            verification_result = self.login_verifier.verify_email(email)
            
            # 2. If result is not clear (risky or custom), try SMTP
            if verification_result.category in [RISKY, CUSTOM]:
                logger.info(f"Login verification gave {verification_result.category} result for {email}, trying SMTP")
                
                # Check if domain has MX records
                _, domain = email.split('@')
                mx_records = self.login_verifier.get_mx_records(domain)
                
                if mx_records:
                    # Verify using SMTP
                    smtp_result = self.login_verifier.verify_smtp(email, mx_records)
                    
                    if smtp_result["is_deliverable"]:
                        # Check if it's a catch-all domain
                        is_catch_all = self.login_verifier.check_catch_all(domain)
                        
                        if is_catch_all:
                            verification_result = verification_result  # Keep original result
                        else:
                            # SMTP says valid
                            verification_result = self.login_verifier.verify_email_smtp(email)
                    elif smtp_result["reason"] == "Mailbox unavailable":
                        # Keep as risky
                        verification_result = verification_result
                    else:
                        # SMTP says invalid
                        verification_result = self.login_verifier.verify_email_smtp(email)
            
            # 3. If still not clear, try Microsoft API for Microsoft domains
            if verification_result.category in [RISKY, CUSTOM]:
                if domain in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                    logger.info(f"SMTP verification gave {verification_result.category} result for {email}, trying Microsoft API")
                    
                    api_result = self.login_verifier.verify_microsoft_api(email)
                    if api_result and api_result.category in [VALID, INVALID]:
                        verification_result = api_result
            
            # 4. If still not clear, mark as risky
            if verification_result.category in [CUSTOM]:
                logger.info(f"All verification methods gave unclear results for {email}, marking as risky")
                verification_result = type(verification_result)(
                    email=email,
                    category=RISKY,
                    reason="Could not determine email validity after trying all methods",
                    provider=verification_result.provider,
                    details=verification_result.details
                )
        else:
            # Without verification loop, just use login verification
            verification_result = self.login_verifier.verify_email(email)
        
        # Convert verification result to dictionary
        result = {
            "email": email,
            "category": verification_result.category,
            "reason": verification_result.reason,
            "provider": verification_result.provider,
            "method": "login" if not hasattr(verification_result, 'details') or not verification_result.details or 'method' not in verification_result.details else verification_result.details['method']
        }
        
        # Update statistics
        category = result["category"]
        self.stats["domains"][domain][category] += 1
        self.stats["domains"][domain]["total"] += 1
        self.stats["total"][category] += 1
        self.stats["total"]["total"] += 1
        
        # Save to data folder
        self.settings.add_email_to_data(email, category)
        
        return result
    
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
    
    def batch_verify(self, emails):
        """
        Verify multiple email addresses.
        
        Args:
            emails: List of email addresses to verify
            
        Returns:
            Dictionary with verification results
        """
        self.stats["total"]["start_time"] = datetime.now()
        
        results = {
            VALID: [],
            INVALID: [],
            RISKY: [],
            CUSTOM: []
        }
        
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
                category = result["category"]
                results[category].append(result)
        else:
            # Single-terminal verification
            for email in emails:
                result = self.verify_email(email)
                category = result["category"]
                results[category].append(result)
                
                # Add a delay between checks to avoid rate limiting
                time.sleep(random.uniform(1, 2))
        
        self.stats["total"]["end_time"] = datetime.now()
        
        return results
    
    def verify_risky_and_custom(self, results):
        """
        Further verify risky and custom emails using verifier2.
        
        Args:
            results: Dictionary with verification results
            
        Returns:
            Updated results
        """
        if not self.bounce_verifier:
            logger.warning("Bounce verifier not initialized. Cannot verify risky/custom emails.")
            return results
        
        # Combine risky and custom emails
        emails_to_verify = [result["email"] for result in results[RISKY] + results[CUSTOM]]
        
        if not emails_to_verify:
            return results
        
        # Start verification
        batch_id = self.bounce_verifier.start_verification(emails_to_verify)
        
        # Return the batch ID so the user can check results later
        return batch_id
    
    def save_results(self, results):
        """
        Save verification results to CSV files.
        
        Args:
            results: Dictionary with verification results
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Create results directory
        results_dir = os.path.join(self.output_dir, f"verification_{timestamp}")
        os.makedirs(results_dir, exist_ok=True)
        
        # Save each category to a separate file
        for category in [VALID, INVALID, RISKY, CUSTOM]:
            file_path = os.path.join(results_dir, f"{category}_emails.csv")
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Email", "Provider", "Reason", "Method"])
                
                for result in results[category]:
                    writer.writerow([
                        result["email"],
                        result["provider"],
                        result["reason"],
                        result["method"]
                    ])
        
        # Save statistics
        stats_file = os.path.join(results_dir, "statistics.csv")
        with open(stats_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Domain", "Valid", "Invalid", "Risky", "Custom", "Total"])
            
            # Write domain statistics
            for domain, stats in self.stats["domains"].items():
                writer.writerow([
                    domain,
                    stats[VALID],
                    stats[INVALID],
                    stats[RISKY],
                    stats[CUSTOM],
                    stats["total"]
                ])
            
            # Write total statistics
            writer.writerow([
                "TOTAL",
                self.stats["total"][VALID],
                self.stats["total"][INVALID],
                self.stats["total"][RISKY],
                self.stats["total"][CUSTOM],
                self.stats["total"]["total"]
            ])
            
            # Write time information
            if self.stats["total"]["start_time"] and self.stats["total"]["end_time"]:
                duration = (self.stats["total"]["end_time"] - self.stats["total"]["start_time"]).total_seconds()
                writer.writerow([])
                writer.writerow(["Start Time", self.stats["total"]["start_time"].strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow(["End Time", self.stats["total"]["end_time"].strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow(["Duration (seconds)", duration])
        
        # Save verification statistics for later analysis
        verification_name = f"verification_{timestamp}"
        statistics = self.get_statistics()
        self.settings.save_verification_statistics(verification_name, statistics)
        
        return results_dir
    
    def get_statistics(self):
        """
        Get detailed statistics for the verification results.
        """
        statistics = {
            "valid": {
                "total": self.stats["total"][VALID],
                "reasons": {}
            },
            "invalid": {
                "total": self.stats["total"][INVALID],
                "reasons": {}
            },
            "risky": {
                "total": self.stats["total"][RISKY],
                "reasons": {}
            },
            "custom": {
                "total": self.stats["total"][CUSTOM],
                "reasons": {}
            },
            "domains": self.stats["domains"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return statistics
    
    def print_statistics(self):
        """Print verification statistics to the console."""
        print("\nVerification Statistics:")
        print("-" * 80)
        print(f"{'Domain':<30} | {'Valid':<8} | {'Invalid':<8} | {'Risky':<8} | {'Custom':<8} | {'Total':<8}")
        print("-" * 80)
        
        # Print domain statistics
        for domain, stats in sorted(self.stats["domains"].items()):
            print(f"{domain:<30} | {stats[VALID]:<8} | {stats[INVALID]:<8} | {stats[RISKY]:<8} | {stats[CUSTOM]:<8} | {stats['total']:<8}")
        
        # Print total statistics
        print("-" * 80)
        print(f"{'TOTAL':<30} | {self.stats['total'][VALID]:<8} | {self.stats['total'][INVALID]:<8} | {self.stats['total'][RISKY]:<8} | {self.stats['total'][CUSTOM]:<8} | {self.stats['total']['total']:<8}")
        
        # Print time information
        if self.stats["total"]["start_time"] and self.stats["total"]["end_time"]:
            duration = (self.stats["total"]["end_time"] - self.stats["total"]["start_time"]).total_seconds()
            print("-" * 80)
            print(f"Start Time: {self.stats['total']['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"End Time: {self.stats['total']['end_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Duration: {duration:.2f} seconds")
        
        print("-" * 80)


def main():
    """Main function to run the unified email verifier."""
    print("\nUnified Email Verification System")
    print("===============================\n")
    
    # Initialize settings
    settings = Settings()
    
    # Initialize verifier with default skip domains
    skip_domains = [
        "example.com",
        "test.com",
        "domain.com",
        "yourdomain.com",
        "mydomain.com"
    ]
    
    # Add domains from whitelist
    skip_domains.extend(settings.get_whitelisted_domains())
    
    verifier = UnifiedEmailVerifier(skip_domains=skip_domains)
    
    while True:
        print("\nOptions:")
        print("1. Verify Emails")
        print("2. Get Final Response")
        print("3. Get Status")
        print("4. Get Statistics")
        print("5. Settings")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ")
        
        if choice == "1":
            # Verify Emails
            print("\nVerify Emails:")
            print("1. Verify a single email")
            print("2. Verify a bulk of emails")
            
            verify_choice = input("\nEnter your choice (1-2): ")
            
            if verify_choice == "1":
                # Verify single email
                email = input("\nEnter the email to verify: ")
                
                print("\nVerifying email...")
                result = verifier.verify_email(email)
                
                print(f"\nResult: {result['category']} - {result['reason']}")
                print(f"Method: {result['method']}")
                
                # Ask if user wants to save the result
                save_choice = input("\nDo you want to save this result? (y/n): ")
                if save_choice.lower() == 'y':
                    results = {
                        VALID: [],
                        INVALID: [],
                        RISKY: [],
                        CUSTOM: []
                    }
                    results[result['category']].append(result)
                    results_dir = verifier.save_results(results)
                    print(f"\nResults saved to {results_dir}")
                
                # If the result is risky or custom, offer to verify further
                if result['category'] in [RISKY, CUSTOM]:
                    further_verify = input("\nThis email is categorized as risky/custom. Do you want to verify it further using SMTP? (y/n): ")
                    if further_verify.lower() == 'y':
                        # Get SMTP credentials if not already set
                        if not verifier.bounce_verifier:
                            # Check if there are accounts in settings
                            smtp_accounts = settings.get_smtp_accounts()
                            
                            if smtp_accounts:
                                print(f"Found {len(smtp_accounts)} email accounts in settings.")
                                use_existing = input("Do you want to use these accounts? (y/n): ")
                                
                                if use_existing.lower() == 'y':
                                    # Use the first account
                                    account = smtp_accounts[0]
                                    verifier.set_bounce_verifier(
                                        account["smtp_server"],
                                        account["smtp_port"],
                                        account["imap_server"],
                                        account["imap_port"],
                                        account["email"],
                                        account["password"]
                                    )
                                else:
                                    # Get new credentials
                                    print("\nPlease provide your email server details for SMTP verification:")
                                    smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                                    smtp_port = int(input("SMTP port (e.g., 587): "))
                                    imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                                    imap_port = int(input("IMAP port (e.g., 993): "))
                                    email_address = input("Your email address: ")
                                    password = input("Your email password: ")
                                    
                                    verifier.set_bounce_verifier(
                                        smtp_server, smtp_port, imap_server, imap_port, email_address, password
                                    )
                                    
                                    # Ask if user wants to save these credentials
                                    save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                                    if save_creds.lower() == 'y':
                                        settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                                        print("Credentials saved to settings.")
                            else:
                                # No accounts in settings, get new credentials
                                print("\nPlease provide your email server details for SMTP verification:")
                                smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                                smtp_port = int(input("SMTP port (e.g., 587): "))
                                imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                                imap_port = int(input("IMAP port (e.g., 993): "))
                                email_address = input("Your email address: ")
                                password = input("Your email password: ")
                                
                                verifier.set_bounce_verifier(
                                    smtp_server, smtp_port, imap_server, imap_port, email_address, password
                                )
                                
                                # Ask if user wants to save these credentials
                                save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                                if save_creds.lower() == 'y':
                                    settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                                    print("Credentials saved to settings.")
                        
                        # Verify further
                        results = {
                            VALID: [],
                            INVALID: [],
                            RISKY: [result] if result['category'] == RISKY else [],
                            CUSTOM: [result] if result['category'] == CUSTOM else []
                        }
                        
                        print("\nStarting SMTP verification...")
                        batch_id = verifier.verify_risky_and_custom(results)
                        
                        print(f"\nVerification started with batch ID: {batch_id}")
                        print("Please wait for bounce-back responses (this may take a few minutes).")
                        print("You can check the results later using option 2 (Get Final Response).")
            
            elif verify_choice == "2":
                # Verify bulk emails
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
                valid_count = len(results[VALID])
                invalid_count = len(results[INVALID])
                risky_count = len(results[RISKY])
                custom_count = len(results[CUSTOM])
                
                print("\nVerification Summary:")
                print(f"Valid emails: {valid_count}")
                print(f"Invalid emails: {invalid_count}")
                print(f"Risky emails: {risky_count}")
                print(f"Custom emails: {custom_count}")
                
                # Save results
                save_choice = input("\nDo you want to save these results? (y/n): ")
                if save_choice.lower() == 'y':
                    results_dir = verifier.save_results(results)
                    print(f"\nResults saved to {results_dir}")
                
                # If there are risky or custom emails, offer to verify further
                if risky_count > 0 or custom_count > 0:
                    further_verify = input(f"\nThere are {risky_count + custom_count} risky/custom emails. Do you want to verify them further using SMTP? (y/n): ")
                    if further_verify.lower() == 'y':
                        # Get SMTP credentials if not already set
                        if not verifier.bounce_verifier:
                            # Check if there are accounts in settings
                            smtp_accounts = settings.get_smtp_accounts()
                            
                            if smtp_accounts:
                                print(f"Found {len(smtp_accounts)} email accounts in settings.")
                                use_existing = input("Do you want to use these accounts? (y/n): ")
                                
                                if use_existing.lower() == 'y':
                                    # Use the first account
                                    account = smtp_accounts[0]
                                    verifier.set_bounce_verifier(
                                        account["smtp_server"],
                                        account["smtp_port"],
                                        account["imap_server"],
                                        account["imap_port"],
                                        account["email"],
                                        account["password"]
                                    )
                                else:
                                    # Get new credentials
                                     
                                    # Get new credentials
                                    print("\nPlease provide your email server details for SMTP verification:")
                                    smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                                    smtp_port = int(input("SMTP port (e.g., 587): "))
                                    imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                                    imap_port = int(input("IMAP port (e.g., 993): "))
                                    email_address = input("Your email address: ")
                                    password = input("Your email password: ")
                                    
                                    verifier.set_bounce_verifier(
                                        smtp_server, smtp_port, imap_server, imap_port, email_address, password
                                    )
                                    
                                    # Ask if user wants to save these credentials
                                    save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                                    if save_creds.lower() == 'y':
                                        settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                                        print("Credentials saved to settings.")
                            else:
                                # No accounts in settings, get new credentials
                                print("\nPlease provide your email server details for SMTP verification:")
                                smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                                smtp_port = int(input("SMTP port (e.g., 587): "))
                                imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                                imap_port = int(input("IMAP port (e.g., 993): "))
                                email_address = input("Your email address: ")
                                password = input("Your email password: ")
                                
                                verifier.set_bounce_verifier(
                                    smtp_server, smtp_port, imap_server, imap_port, email_address, password
                                )
                                
                                # Ask if user wants to save these credentials
                                save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                                if save_creds.lower() == 'y':
                                    settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                                    print("Credentials saved to settings.")
                        
                        # Verify further
                        print("\nStarting SMTP verification...")
                        batch_id = verifier.verify_risky_and_custom(results)
                        
                        print(f"\nVerification started with batch ID: {batch_id}")
                        print("Please wait for bounce-back responses (this may take a few minutes).")
                        print("You can check the results later using option 2 (Get Final Response).")
        
        elif choice == "2":
            # Get Final Response
            # This option is for checking the results of previous SMTP verifications
            if not verifier.bounce_verifier:
                # Check if there are accounts in settings
                smtp_accounts = settings.get_smtp_accounts()
                
                if smtp_accounts:
                    print(f"Found {len(smtp_accounts)} email accounts in settings.")
                    use_existing = input("Do you want to use these accounts? (y/n): ")
                    
                    if use_existing.lower() == 'y':
                        # Use the first account
                        account = smtp_accounts[0]
                        verifier.set_bounce_verifier(
                            account["smtp_server"],
                            account["smtp_port"],
                            account["imap_server"],
                            account["imap_port"],
                            account["email"],
                            account["password"]
                        )
                    else:
                        # Get new credentials
                        print("\nPlease provide your email server details for SMTP verification:")
                        smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                        smtp_port = int(input("SMTP port (e.g., 587): "))
                        imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                        imap_port = int(input("IMAP port (e.g., 993): "))
                        email_address = input("Your email address: ")
                        password = input("Your email password: ")
                        
                        verifier.set_bounce_verifier(
                            smtp_server, smtp_port, imap_server, imap_port, email_address, password
                        )
                        
                        # Ask if user wants to save these credentials
                        save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                        if save_creds.lower() == 'y':
                            settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                            print("Credentials saved to settings.")
                else:
                    # No accounts in settings, get new credentials
                    print("\nPlease provide your email server details for SMTP verification:")
                    smtp_server = input("SMTP server (e.g., smtp.gmail.com): ")
                    smtp_port = int(input("SMTP port (e.g., 587): "))
                    imap_server = input("IMAP server (e.g., imap.gmail.com): ")
                    imap_port = int(input("IMAP port (e.g., 993): "))
                    email_address = input("Your email address: ")
                    password = input("Your email password: ")
                    
                    verifier.set_bounce_verifier(
                        smtp_server, smtp_port, imap_server, imap_port, email_address, password
                    )
                    
                    # Ask if user wants to save these credentials
                    save_creds = input("Do you want to save these credentials for future use? (y/n): ")
                    if save_creds.lower() == 'y':
                        settings.add_smtp_account(smtp_server, smtp_port, imap_server, imap_port, email_address, password)
                        print("Credentials saved to settings.")
            
            # Get all batches
            batches = verifier.bounce_verifier.get_all_batches()
            pending_batches = [batch for batch in batches if batch['status'] == "Waiting for checking"]
            
            if not pending_batches:
                print("\nNo batches waiting for checking.")
                continue
            
            print("\nBatches waiting for checking:")
            for i, batch in enumerate(pending_batches, 1):
                print(f"{i}. {batch['batch_id']} - Created: {batch['created']} - Pending: {batch['pending']}")
            
            batch_index = input("\nEnter the number of the batch to check (or 0 to cancel): ")
            try:
                batch_index = int(batch_index)
                if batch_index == 0:
                    continue
                
                if 1 <= batch_index <= len(pending_batches):
                    batch_id = pending_batches[batch_index - 1]['batch_id']
                    print(f"\nChecking responses for batch {batch_id}...")
                    
                    invalid_count, valid_count = verifier.bounce_verifier.process_responses(batch_id)
                    print(f"\nProcessed responses: {invalid_count} invalid, {valid_count} valid emails identified.")
                else:
                    print("\nInvalid selection.")
            except ValueError:
                print("\nInvalid input. Please enter a number.")
        
        elif choice == "3":
            # Get Status
            if not verifier.bounce_verifier:
                print("\nSMTP verification has not been set up yet.")
                continue
            
            # Get all batches
            batches = verifier.bounce_verifier.get_all_batches()
            
            if not batches:
                print("\nNo verification batches found.")
                continue
            
            print("\nVerification Batches:")
            print("-" * 100)
            print(f"{'Batch ID':<36} | {'Created':<20} | {'Status':<18} | {'Total':<6} | {'Valid':<6} | {'Invalid':<8} | {'Pending':<8}")
            print("-" * 100)
            
            for batch in batches:
                print(f"{batch['batch_id']:<36} | {batch['created']:<20} | {batch['status']:<18} | {batch['total_emails']:<6} | {batch['valid']:<6} | {batch['invalid']:<8} | {batch['pending']:<8}")
        
        elif choice == "4":
            # Get Statistics
            print("\nStatistics Options:")
            print("1. Current verification statistics")
            print("2. Saved verification statistics")
            
            stats_choice = input("\nEnter your choice (1-2): ")
            
            if stats_choice == "1":
                # Show current verification statistics
                verifier.print_statistics()
            
            elif stats_choice == "2":
                # Show saved verification statistics
                verification_names = settings.get_verification_names()
                
                if not verification_names:
                    print("\nNo saved verification statistics found.")
                    continue
                
                print("\nSaved Verifications:")
                for i, name in enumerate(verification_names, 1):
                    print(f"{i}. {name}")
                
                verification_index = input("\nEnter the number of the verification to view (or 0 to cancel): ")
                try:
                    verification_index = int(verification_index)
                    if verification_index == 0:
                        continue
                    
                    if 1 <= verification_index <= len(verification_names):
                        verification_name = verification_names[verification_index - 1]
                        statistics = settings.get_verification_statistics(verification_name)
                        
                        if not statistics:
                            print(f"\nNo statistics found for '{verification_name}'")
                            continue
                        
                        print(f"\nStatistics for '{verification_name}':")
                        print("-" * 80)
                        
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
            print("6. Verification loop settings")
            
            settings_choice = input("\nEnter your choice (1-6): ")
            
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
            
            elif settings_choice == "6":
                # Verification loop settings
                print("\nVerification Loop Settings:")
                current_enabled = settings.is_enabled("verification_loop_enabled")
                
                print(f"Verification loop is currently {'enabled' if current_enabled else 'disabled'}")
                
                enable = input("\nEnable verification loop? (y/n): ")
                if enable.lower() == 'y':
                    settings.set("verification_loop_enabled", "True", True)
                    print("\nVerification loop enabled")
                else:
                    settings.set("verification_loop_enabled", "False", False)
                    print("\nVerification loop disabled")
        
        elif choice == "6":
            # Exit
            print("\nExiting Unified Email Verification System. Goodbye!")
            break
        
        else:
            print("\nInvalid choice. Please try again.")


if __name__ == "__main__":
    main()