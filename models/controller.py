import os
import csv
import time
import random
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Import all models
from models.settings_model import SettingsModel
from models.initial_validation_model import InitialValidationModel
from models.smtp_model import SMTPModel
from models.selenium_model import SeleniumModel
from models.api_model import APIModel
from models.sequence_model import SequenceModel
from models.judgment_model import JudgmentModel
from models.multi_terminal_model import MultiTerminalModel
from models.results_model import ResultsModel
from models.statistics_model import StatisticsModel
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class VerificationController:
    """Controller class that manages all verification models and processes."""
    
    def __init__(self):
        """Initialize the controller and all models."""
        # Initialize settings first as other models depend on it
        self.settings_model = SettingsModel()
        
        # Initialize all other models
        self.initial_validation_model = InitialValidationModel(self.settings_model)
        self.smtp_model = SMTPModel(self.settings_model)
        self.selenium_model = SeleniumModel(self.settings_model)
        self.api_model = APIModel(self.settings_model)
        self.sequence_model = SequenceModel(self.settings_model)
        self.judgment_model = JudgmentModel(self.settings_model)
        self.multi_terminal_model = MultiTerminalModel(self.settings_model)
        self.results_model = ResultsModel(self.settings_model)
        self.statistics_model = StatisticsModel(self.settings_model)
        
        # Cache for verification results
        self.result_cache: Dict[str, EmailVerificationResult] = {}
        
        # Verification history tracking
        self.verification_history: Dict[str, List[Dict[str, str]]] = {}
        
        # Lock for thread safety
        self.lock = self.multi_terminal_model.get_lock()
    
    def verify_email(self, email: str) -> EmailVerificationResult:
        """
        Verify an email address using the appropriate verification sequence.
        
        Args:
            email: The email address to verify
            
        Returns:
            EmailVerificationResult: The verification result
        """
        # Initialize verification history
        with self.lock:
            self.verification_history[email] = []
        
        self.add_to_history(email, "Verification started")
        
        # Check if email exists in data files first
        exists, category = self.results_model.check_email_in_data(email)
        if exists:
            self.add_to_history(email, f"Email found in {category} list - using cached result")
            return EmailVerificationResult(
                email=email,
                category=category,
                reason=f"Email found in {category} list",
                provider="cached"
            )
        
        # Check cache next
        with self.lock:
            if email in self.result_cache:
                return self.result_cache[email]
        
        # Step 1: Initial validation
        validation_result = self.initial_validation_model.validate_email(email)
        if validation_result:
            with self.lock:
                self.result_cache[email] = validation_result
            self.results_model.save_result(validation_result)
            self.save_history(email, validation_result.category)
            return validation_result
        
        # Extract domain and get MX records
        _, domain = email.split('@')
        mx_records = self.initial_validation_model.get_mx_records(domain)
        
        # Step 2: Identify provider and determine verification sequence
        provider, login_url = self.initial_validation_model.identify_provider(email)
        self.add_to_history(email, f"Provider identified: {provider}")
        
        # Step 3: Execute the appropriate verification sequence
        verification_sequence = self.sequence_model.get_verification_sequence(provider)
        
        # Execute each verification method in the sequence
        results = []
        for method_name in verification_sequence:
            self.add_to_history(email, f"Trying verification method: {method_name}")
            
            if method_name == "api":
                # API verification
                if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                    result = self.api_model.verify_microsoft_api(email)
                elif provider in ['gmail.com', 'googlemail.com']:
                    result = self.api_model.verify_google_api(email)
                else:
                    result = self.api_model.verify_generic_api(email, provider)
            
            elif method_name == "selenium":
                # Selenium verification
                result = self.selenium_model.verify_login(email, provider, login_url)
            
            elif method_name == "smtp":
                # SMTP verification
                result = self.smtp_model.verify_email_smtp(email, mx_records)
            
            else:
                self.add_to_history(email, f"Unknown verification method: {method_name}")
                continue
            
            # If we got a result and it's definitive, return it
            if result and result.category in [VALID, INVALID]:
                with self.lock:
                    self.result_cache[email] = result
                self.results_model.save_result(result)
                self.save_history(email, result.category)
                return result
            
            # Otherwise, add to results list for judgment
            if result:
                results.append(result)
        
        # Step 4: Make a judgment based on all results
        final_result = self.judgment_model.make_judgment(email, results)
        
        with self.lock:
            self.result_cache[email] = final_result
        self.results_model.save_result(final_result)
        self.save_history(email, final_result.category)
        
        return final_result
    
    def batch_verify(self, emails: List[str]) -> Dict[str, EmailVerificationResult]:
        """
        Verify multiple email addresses.
        
        Args:
            emails: List of emails to verify
            
        Returns:
            Dict[str, EmailVerificationResult]: Dictionary of verification results
        """
        # Check if multi-terminal support is enabled
        if self.settings_model.is_enabled("multi_terminal_enabled") and len(emails) > 1:
            return self.multi_terminal_model.batch_verify(emails, self.verify_email)
        else:
            # Single-terminal verification
            results = {}
            for email in emails:
                results[email] = self.verify_email(email)
                # Add a delay between checks to avoid rate limiting
                time.sleep(random.uniform(2, 4))
            return results
    
    def add_to_history(self, email: str, event: str) -> None:
        """
        Add an event to the verification history for an email.
        
        Args:
            email: The email address
            event: The event description
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with self.lock:
            if email not in self.verification_history:
                self.verification_history[email] = []
            
            event_entry = {
                "timestamp": timestamp,
                "event": event
            }
            
            self.verification_history[email].append(event_entry)
        
        # Save to disk immediately
        self.results_model.save_history_event(email, event_entry)
        
        logger.info(f"{email} - {event}")
    
    def save_history(self, email: str, category: str) -> None:
        """
        Save the verification history for an email to the appropriate JSON file.
        
        Args:
            email: The email address
            category: The verification category (valid, invalid, risky, custom)
        """
        if email not in self.verification_history:
            return
        
        self.results_model.save_history(email, category, self.verification_history[email])
    
    def batch_verification_menu(self) -> None:
        """Display the batch verification menu and handle user input."""
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
                    return
            except Exception as e:
                print(f"\nError reading file: {e}")
                return
        
        elif bulk_choice == "2":
            # Enter manually
            emails_input = input("\nEnter emails separated by commas: ")
            emails = [email.strip() for email in emails_input.split(",") if '@' in email.strip()]
            
            if not emails:
                print("\nNo valid emails provided.")
                return
        
        # Ask if multi-terminal should be used
        if len(emails) > 1:
            use_multi = input("\nUse multi-terminal for faster verification? (y/n): ")
            if use_multi.lower() == 'y':
                self.multi_terminal_model.enable_multi_terminal()
                terminal_count = input(f"\nEnter number of terminals to use (1-{min(8, len(emails))}): ")
                try:
                    self.multi_terminal_model.set_terminal_count(min(int(terminal_count), 8, len(emails)))
                except ValueError:
                    self.multi_terminal_model.set_terminal_count(min(2, len(emails)))
                
                # Ask if real multiple terminals should be used
                use_real = input("\nUse real multiple terminals? (y/n): ")
                if use_real.lower() == 'y':
                    self.settings_model.set("real_multiple_terminals", "True", True)
                    print("\nUsing real multiple terminals (recommended limit: 4 terminals)")
                else:
                    self.settings_model.set("real_multiple_terminals", "False", False)
            else:
                self.multi_terminal_model.disable_multi_terminal()
        
        # Verify emails
        print(f"\nVerifying {len(emails)} emails...")
        results = self.batch_verify(emails)
        
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
            statistics = self.statistics_model.get_statistics()
            self.settings_model.save_verification_statistics(verification_name, statistics)
            print(f"\nStatistics saved as '{verification_name}'")
    
    def show_results_summary(self) -> None:
        """Display a summary of verification results."""
        summary = self.results_model.get_results_summary()
        print("\nResults Summary:")
        print(f"Valid emails: {summary[VALID]}")
        print(f"Invalid emails: {summary[INVALID]}")
        print(f"Risky emails: {summary[RISKY]}")
        print(f"Custom emails: {summary[CUSTOM]}")
        print(f"\nTotal: {sum(summary.values())}")
        
        print("\nResults are saved in the following files:")
        for category in [VALID, INVALID, RISKY, CUSTOM]:
            print(f"{category.capitalize()} emails: ./data/{category.capitalize()}.csv")
    
    def show_statistics_menu(self) -> None:
        """Display the statistics menu and handle user input."""
        print("\nStatistics Options:")
        print("1. Global statistics")
        print("2. Specific verification statistics")
        print("3. Verification history")
        
        stats_choice = input("\nEnter your choice (1-3): ")
        
        if stats_choice == "1":
            # Show global statistics
            self.statistics_model.show_global_statistics()
        
        elif stats_choice == "2":
            # Show specific verification statistics
            self.statistics_model.show_specific_verification_statistics()
        
        elif stats_choice == "3":
            # Show verification history
            self.statistics_model.show_verification_history_menu()
    
    def settings_menu(self) -> None:
        """Display the settings menu and handle user input."""
        print("\nSettings:")
        print("1. Multi-terminal settings")
        print("2. Browser settings")
        print("3. Domain lists")
        print("4. SMTP accounts")
        print("5. Proxy settings")
        print("6. Screenshot settings")
        print("7. Rate limiting settings")
        
        settings_choice = input("\nEnter your choice (1-7): ")
        
        if settings_choice == "1":
            # Multi-terminal settings
            self.settings_model.configure_multi_terminal_settings()
        
        elif settings_choice == "2":
            # Browser settings
            self.settings_model.configure_browser_settings()
        
        elif settings_choice == "3":
            # Domain lists
            self.settings_model.configure_domain_lists()
        
        elif settings_choice == "4":
            # SMTP accounts
            self.settings_model.configure_smtp_accounts()
        
        elif settings_choice == "5":
            # Proxy settings
            self.settings_model.configure_proxy_settings()
        
        elif settings_choice == "6":
            # Screenshot settings
            self.settings_model.configure_screenshot_settings()
        
        elif settings_choice == "7":
            # Rate limiting settings
            self.settings_model.configure_rate_limiting_settings()
