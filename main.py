#!/usr/bin/env python3
import os
import sys
import logging
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
        "./statistics/history"
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
    
    # Start the application
    main_menu()
