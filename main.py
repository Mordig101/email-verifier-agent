#!/usr/bin/env python3
import os
import sys
import time
import logging
import argparse
import csv
from typing import Dict, List, Any, Optional

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
from models.controller import VerificationController
from models.common import VALID, INVALID, RISKY, CUSTOM

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler("email_verifier.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_required_directories():
    """Create all required directories for the application."""
    directories = [
        "./data",
        "./results",
        "./screenshots",
        "./statistics",
        "./statistics/history",
        "./terminal",  # Add terminal directory for multi-terminal results
        "./driver"     # Add driver directory for WebDriver executables
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    
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
        file_path = os.path.join("./data", file)
        if not os.path.exists(file_path):
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                if file in ["D-blacklist.csv", "D-WhiteList.csv"]:
                    f.write("domain\n")
                else:
                    f.write("email\n")

def auto_verify_from_csv(controller, csv_path, terminal_id=None):
    """
    Automatically verify emails from a CSV file.
    
    Args:
        controller: The verification controller
        csv_path: Path to the CSV file
        terminal_id: Optional terminal ID for logging
    """
    try:
        start_time = time.time()
        
        # Create terminal directory if it doesn't exist
        terminal_dir = "./terminal"
        os.makedirs(terminal_dir, exist_ok=True)
        
        # Create result file for this terminal
        result_file = os.path.join(terminal_dir, f"T{terminal_id}_results.txt")
        
        # Also create a CSV results file
        csv_result_file = os.path.join(terminal_dir, f"T{terminal_id}_results.csv")
        
        # Read emails from CSV
        emails = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                csv_reader = csv.reader(f)
                for row in csv_reader:
                    if row and '@' in row[0]:  # Basic validation
                        emails.append(row[0].strip())
        except UnicodeDecodeError:
            # Try with a different encoding if UTF-8 fails
            with open(csv_path, 'r', encoding='latin-1') as f:
                csv_reader = csv.reader(f)
                for row in csv_reader:
                    if row and '@' in row[0]:  # Basic validation
                        emails.append(row[0].strip())
        
        if not emails:
            logger.warning(f"Terminal {terminal_id}: No valid emails found in the CSV file.")
            print(f"Terminal {terminal_id}: No valid emails found in the CSV file.")
            
            # Write to result file
            with open(result_file, 'w', encoding='utf-8') as f:
                f.write("No valid emails found in the CSV file.\n")
            return
        
        # Remove header if it doesn't look like an email
        if not '@' in emails[0] or emails[0].lower() == "email":
            emails = emails[1:]
        
        if not emails:
            logger.warning(f"Terminal {terminal_id}: No valid emails found in the CSV file after removing header.")
            print(f"Terminal {terminal_id}: No valid emails found in the CSV file after removing header.")
            
            # Write to result file
            with open(result_file, 'w', encoding='utf-8') as f:
                f.write("No valid emails found in the CSV file after removing header.\n")
            return
        
        # Enable multi-terminal support
        controller.multi_terminal_model.enable_multi_terminal()
        controller.multi_terminal_model.set_terminal_count(2)  # Use 2 processes within this terminal
        
        # Disable real multiple terminals since we're already in a terminal
        controller.settings_model.set("real_multiple_terminals", "False", False)
        
        # Verify emails
        prefix = f"Terminal {terminal_id}: " if terminal_id else ""
        logger.info(f"{prefix}Starting verification of {len(emails)} emails")
        print(f"{prefix}Verifying {len(emails)} emails...")
        
        # Write to result file
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(f"Starting verification of {len(emails)} emails at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Initialize CSV results file
        with open(csv_result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Email", "Category", "Reason", "Provider", "Timestamp"])
        
        results = controller.batch_verify(emails)
        
        # Print results and write to result files
        with open(result_file, 'a', encoding='utf-8') as f, open(csv_result_file, 'a', newline='', encoding='utf-8') as csv_f:
            csv_writer = csv.writer(csv_f)
            
            for email, result in results.items():
                status_line = f"Verified {email}... [{result.category}] ; Reason: {result.reason}"
                print(f"{prefix}{status_line}")
                f.write(f"{status_line}\n")
                
                # Add to CSV file
                csv_writer.writerow([
                    email, 
                    result.category, 
                    result.reason,
                    result.provider,
                    time.strftime('%Y-%m-%d %H:%M:%S')
                ])
        
        # Print summary
        valid_count = sum(1 for result in results.values() if result.category == VALID)
        invalid_count = sum(1 for result in results.values() if result.category == INVALID)
        risky_count = sum(1 for result in results.values() if result.category == RISKY)
        custom_count = sum(1 for result in results.values() if result.category == CUSTOM)
        
        elapsed_time = time.time() - start_time
        emails_per_second = len(emails) / elapsed_time if elapsed_time > 0 else 0
        
        summary = [
            f"Verification Summary:",
            f"Valid emails: {valid_count}",
            f"Invalid emails: {invalid_count}",
            f"Risky emails: {risky_count}",
            f"Custom emails: {custom_count}",
            f"Total verified: {len(results)}",
            f"Elapsed time: {elapsed_time:.2f} seconds",
            f"Speed: {emails_per_second:.2f} emails/second"
        ]
        
        # Print summary and write to result file
        with open(result_file, 'a', encoding='utf-8') as f:
            for line in summary:
                print(f"{prefix}{line}")
                f.write(f"{line}\n")
            
            # Add timestamp
            completion_message = f"Completed at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            print(f"{prefix}{completion_message}")
            f.write(f"{completion_message}\n")
        
        # Create completion marker
        completion_marker = os.path.join(terminal_dir, f"T{terminal_id}_completed.txt")
        with open(completion_marker, 'w', encoding='utf-8') as f:
            f.write(f"Completed at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total emails: {len(emails)}\n")
            f.write(f"Valid: {valid_count}, Invalid: {invalid_count}, Risky: {risky_count}, Custom: {custom_count}\n")
            f.write(f"Elapsed time: {elapsed_time:.2f} seconds\n")
        
        logger.info(f"{prefix}Verification completed. Results saved to {result_file} and {csv_result_file}")
        
    except Exception as e:
        error_msg = f"Error in auto verification: {e}"
        logger.error(f"{error_msg}", exc_info=True)
        print(error_msg)
        
        # Write error to result file
        if terminal_id is not None:
            result_file = os.path.join("./terminal", f"T{terminal_id}_results.txt")
            with open(result_file, 'a', encoding='utf-8') as f:
                f.write(f"ERROR: {error_msg}\n")

def main_menu():
    """Display the main menu and handle user input."""
    # Initialize the controller
    controller = VerificationController()
    
    while True:
        print("\nEmail Verification System")
        print("========================")
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
            result = controller.verify_email(email)
            print(f"\nResult: {result}")
            
        elif choice == "2":
            controller.batch_verification_menu()
            
        elif choice == "3":
            controller.show_results_summary()
            
        elif choice == "4":
            controller.show_statistics_menu()
            
        elif choice == "5":
            controller.settings_menu()
            
        elif choice == "6":
            print("\nExiting Email Verification System. Goodbye!")
            break
            
        else:
            print("\nInvalid choice. Please try again.")

if __name__ == "__main__":
    # Create required directories
    create_required_directories()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Email Verification System")
    parser.add_argument("--terminal", type=int, help="Terminal ID for multi-terminal mode")
    parser.add_argument("--csv", type=str, help="Path to CSV file for auto verification")
    parser.add_argument("--auto-verify", action="store_true", help="Auto verify emails without user interaction")
    args = parser.parse_args()
    
    # Check if running in auto-verify mode
    if args.csv and (args.auto_verify or args.terminal is not None):
        # Initialize the controller
        controller = VerificationController()
        
        # Auto verify emails from CSV
        auto_verify_from_csv(controller, args.csv, args.terminal)
    else:
        # Start the normal application
        main_menu()
