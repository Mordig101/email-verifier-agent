import os
import json
import logging
from typing import Dict, List, Any, Optional
from models.common import VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class StatisticsModel:
    """Model for generating and displaying statistics."""
    
    def __init__(self, settings_model):
        """
        Initialize the statistics model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        self.statistics_dir = "./statistics"
        self.history_dir = os.path.join(self.statistics_dir, "history")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get detailed statistics for the verification results.
        
        Returns:
            Dict[str, Any]: The verification statistics
        """
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
        for category in [VALID, INVALID, RISKY, CUSTOM]:
            file_path = f"./data/{category.capitalize()}.csv"
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    import csv
                    reader = csv.reader(f)
                    next(reader)  # Skip header
                    
                    for row in reader:
                        if len(row) >= 3:
                            email, provider, reason = row[0], row[1], row[3] if len(row) > 3 else "Unknown"
                            
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
    
    def show_global_statistics(self) -> None:
        """Display global statistics."""
        statistics = self.get_statistics()
        
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
    
    def show_specific_verification_statistics(self) -> None:
        """Display statistics for a specific verification."""
        verification_names = self.settings_model.get_verification_names()
        
        if not verification_names:
            print("\nNo saved verification statistics found.")
            return
        
        print("\nSaved Verifications:")
        for i, name in enumerate(verification_names, 1):
            print(f"{i}. {name}")
        
        verification_index = input("\nEnter the number of the verification to view: ")
        try:
            verification_index = int(verification_index) - 1
            if 0 <= verification_index < len(verification_names):
                verification_name = verification_names[verification_index]
                statistics = self.settings_model.get_verification_statistics(verification_name)
                
                if not statistics:
                    print(f"\nNo statistics found for '{verification_name}'")
                    return
                
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
    
    def show_verification_history_menu(self) -> None:
        """Display the verification history menu and handle user input."""
        print("\nVerification History Options:")
        print("1. History for a specific email")
        print("2. History for a category")
        
        history_choice = input("\nEnter your choice (1-2): ")
        
        if history_choice == "1":
            # Show history for a specific email
            email = input("\nEnter the email to view history for: ")
            history = self.get_verification_history(email=email)
            
            if not history:
                print(f"\nNo history found for {email}")
                return
            
            print(f"\nVerification History for {email}:")
            print("--------------------------------------------------")
            
            for event in history[email]:
                print(f"{event['timestamp']}: {event['event']}")
        
        elif history_choice == "2":
            # Show history for a category
            print("\nCategories:")
            print(f"1. {VALID}")
            print(f"2. {INVALID}")
            print(f"3. {RISKY}")
            print(f"4. {CUSTOM}")
            
            cat_choice = input("\nEnter your choice (1-4): ")
            
            category_map = {
                "1": VALID,
                "2": INVALID,
                "3": RISKY,
                "4": CUSTOM
            }
            
            if cat_choice in category_map:
                category = category_map[cat_choice]
                history = self.get_verification_history(category=category)
                
                if not history:
                    print(f"\nNo history found for {category} emails")
                    return
                
                print(f"\nVerification History for {category.capitalize()} Emails:")
                print("--------------------------------------------------")
                
                # Show the first 5 emails
                count = 0
                for email, events in history.items():
                    if count >= 5:
                        break
                    
                    print(f"\nEmail: {email}")
                    for event in events:
                        print(f"  {event['timestamp']}: {event['event']}")
                    
                    count += 1
                
                if len(history) > 5:
                    print(f"\n... and {len(history) - 5} more emails")
            else:
                print("\nInvalid choice.")
    
    def get_verification_history(self, email: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        """
        Get verification history for a specific email or category.
        
        Args:
            email: The email address to get history for
            category: The category to get history for
            
        Returns:
            Dict[str, Any]: The verification history
        """
        if email:
            # Get history for a specific email
            for cat in [VALID, INVALID, RISKY, CUSTOM]:
                history_file = os.path.join(self.history_dir, f"{cat}.json")
                try:
                    if os.path.exists(history_file):
                        with open(history_file, 'r', encoding='utf-8') as f:
                            history = json.load(f)
                            if email in history:
                                return {email: history[email]}
                except Exception as e:
                    logger.error(f"Error loading history for {email}: {e}")
            
            return {}
        
        elif category:
            # Get history for a specific category
            history_file = os.path.join(self.history_dir, f"{category}.json")
            try:
                if os.path.exists(history_file):
                    with open(history_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
            except Exception as e:
                logger.error(f"Error loading history for category {category}: {e}")
            
            return {}
        
        else:
            # Get all history
            all_history = {}
            for cat in [VALID, INVALID, RISKY, CUSTOM]:
                history_file = os.path.join(self.history_dir, f"{cat}.json")
                try:
                    if os.path.exists(history_file):
                        with open(history_file, 'r', encoding='utf-8') as f:
                            all_history[cat] = json.load(f)
                except Exception as e:
                    logger.error(f"Error loading history for category {cat}: {e}")
                    all_history[cat] = {}
            
            return all_history