import os
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
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
        os.makedirs(self.statistics_dir, exist_ok=True)
        
        self.history_dir = os.path.join(self.statistics_dir, "history")
        os.makedirs(self.history_dir, exist_ok=True)
        
        # Ensure history JSON files exist for each category
        for category in [VALID, INVALID, RISKY, CUSTOM]:
            history_file = os.path.join(self.history_dir, f"{category}.json")
            if not os.path.exists(history_file):
                with open(history_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=4)
        
        # Create temp history file if it doesn't exist
        temp_history_file = os.path.join(self.history_dir, "temp_history.json")
        if not os.path.exists(temp_history_file):
            with open(temp_history_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, indent=4)
    
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
            "domains": {},
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Process each category
        for category in [VALID, INVALID, RISKY, CUSTOM]:
            file_path = f"./data/{category.capitalize()}.csv"
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        import csv
                        reader = csv.reader(f)
                        next(reader, None)  # Skip header, safely handle empty files
                        
                        for row in reader:
                            if len(row) >= 1:  # At least has an email
                                email = row[0]
                                provider = row[1] if len(row) > 1 else "Unknown"
                                reason = row[3] if len(row) > 3 else "Unknown"
                                
                                # Update category total
                                statistics[category]["total"] += 1
                                
                                # Update reason frequency
                                if reason not in statistics[category]["reasons"]:
                                    statistics[category]["reasons"][reason] = 0
                                statistics[category]["reasons"][reason] += 1
                                
                                # Update domain statistics
                                if '@' in email:
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
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
        
        return statistics
    
    def show_global_statistics(self) -> None:
        """Display global statistics."""
        statistics = self.get_statistics()
        
        print("\nGlobal Statistics:")
        print("-" * 50)
        print(f"Generated on: {statistics.get('timestamp', 'Unknown')}")
        
        print("\nCategory Totals:")
        print(f"Valid emails: {statistics['valid']['total']}")
        print(f"Invalid emails: {statistics['invalid']['total']}")
        print(f"Risky emails: {statistics['risky']['total']}")
        print(f"Custom emails: {statistics['custom']['total']}")
        print(f"Total emails: {sum(statistics[cat]['total'] for cat in ['valid', 'invalid', 'risky', 'custom'])}")
        
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
                print(f"Generated on: {statistics.get('timestamp', 'Unknown')}")
                
                print("\nCategory Totals:")
                print(f"Valid emails: {statistics['valid']['total']}")
                print(f"Invalid emails: {statistics['invalid']['total']}")
                print(f"Risky emails: {statistics['risky']['total']}")
                print(f"Custom emails: {statistics['custom']['total']}")
                print(f"Total emails: {sum(statistics[cat]['total'] for cat in ['valid', 'invalid', 'risky', 'custom'])}")
                
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
                    
                # Ask if user wants to see a specific email in detail
                see_detail = input("\nDo you want to see detailed history for a specific email? (y/n): ")
                if see_detail.lower() == 'y':
                    detail_email = input("\nEnter the email to view detailed history for: ")
                    if detail_email in history:
                        print(f"\nDetailed History for {detail_email}:")
                        print("--------------------------------------------------")
                        for event in history[detail_email]:
                            print(f"{event['timestamp']}: {event['event']}")
                    else:
                        print(f"\nNo history found for {detail_email}")
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
                            content = f.read().strip()
                            if content:
                                try:
                                    history = json.loads(content)
                                    if email in history:
                                        return {email: history[email]}
                                except json.JSONDecodeError as je:
                                    logger.error(f"JSON parsing error in {cat} history file: {je}")
                                    self._repair_history_file(history_file)
                except Exception as e:
                    logger.error(f"Error loading history for {email}: {e}")
            
            # Also check temp history
            temp_history_file = os.path.join(self.history_dir, "temp_history.json")
            try:
                if os.path.exists(temp_history_file):
                    with open(temp_history_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            try:
                                temp_history = json.loads(content)
                                if email in temp_history:
                                    return {email: temp_history[email]}
                            except json.JSONDecodeError as je:
                                logger.error(f"JSON parsing error in temp history file: {je}")
                                self._repair_temp_history_file(temp_history_file)
            except Exception as e:
                logger.error(f"Error loading temp history for {email}: {e}")
            
            return {}
        
        elif category:
            # Get history for a specific category
            history_file = os.path.join(self.history_dir, f"{category}.json")
            try:
                if os.path.exists(history_file):
                    with open(history_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            try:
                                return json.loads(content)
                            except json.JSONDecodeError as je:
                                logger.error(f"JSON parsing error in {category} history file: {je}")
                                self._repair_history_file(history_file)
                                return {}
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
                            content = f.read().strip()
                            if content:
                                try:
                                    all_history[cat] = json.loads(content)
                                except json.JSONDecodeError as je:
                                    logger.error(f"JSON parsing error in {cat} history file: {je}")
                                    self._repair_history_file(history_file)
                                    all_history[cat] = {}
                            else:
                                all_history[cat] = {}
                except Exception as e:
                    logger.error(f"Error loading history for category {cat}: {e}")
                    all_history[cat] = {}
            
            return all_history
    
    def _repair_history_file(self, file_path: str) -> None:
        """
        Attempt to repair a corrupted history file.
        
        Args:
            file_path: Path to the history file
        """
        try:
            # Create a new clean history dictionary
            new_history = {}
            
            # Try to read the file line by line to extract valid JSON objects
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
                
            # Basic attempt to extract the main JSON object
            try:
                # Find the outermost braces
                start_idx = file_content.find('{')
                end_idx = file_content.rfind('}')
                
                if start_idx >= 0 and end_idx > start_idx:
                    # Extract what looks like valid JSON
                    possible_json = file_content[start_idx:end_idx+1]
                    new_history = json.loads(possible_json)
            except:
                # If extraction failed, start with empty dictionary
                logger.error(f"Could not extract valid JSON from history file: {file_path}")
                
            # Write the repaired file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(new_history, f, indent=4)
                
            logger.info(f"Repaired history file: {file_path}")
        except Exception as e:
            logger.error(f"Error repairing history file: {e}")
            # As a last resort, recreate the file with an empty dictionary
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=4)
                    logger.info(f"Reset history file to empty state: {file_path}")
            except:
                logger.error(f"Failed to reset history file: {file_path}")
    
    def _repair_temp_history_file(self, file_path: str, email_to_remove: str = None) -> None:
        """
        Attempt to repair a corrupted temp history file.
        
        Args:
            file_path: Path to the temp history file
            email_to_remove: Optional email to remove during repair
        """
        try:
            # Create a new clean history dictionary
            new_history = {}
            
            # Try to read the file line by line to extract valid JSON objects
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
                
            # Basic attempt to extract the main JSON object
            try:
                # Find the outermost braces
                start_idx = file_content.find('{')
                end_idx = file_content.rfind('}')
                
                if start_idx >= 0 and end_idx > start_idx:
                    # Extract what looks like valid JSON
                    possible_json = file_content[start_idx:end_idx+1]
                    new_history = json.loads(possible_json)
                    
                    # Remove the specified email if needed
                    if email_to_remove and email_to_remove in new_history:
                        del new_history[email_to_remove]
            except:
                # If extraction failed, start with empty dictionary
                logger.error("Could not extract valid JSON from temp history file")
                
            # Write the repaired file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(new_history, f, indent=4)
                
            logger.info(f"Repaired temp history file: {file_path}")
        except Exception as e:
            logger.error(f"Error repairing temp history file: {e}")
            # As a last resort, recreate the file with an empty dictionary
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=4)
                    logger.info("Reset temp history file to empty state")
            except:
                logger.error("Failed to reset temp history file")
    
    def save_verification_history(self, email: str, category: str, history: List[Dict[str, str]]) -> bool:
        """
        Save verification history for an email to the appropriate JSON file.
        
        Args:
            email: The email address
            category: The category (valid, invalid, risky, custom)
            history: List of history events
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            history_file = os.path.join(self.history_dir, f"{category}.json")
            
            # Load existing history
            existing_history = {}
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        try:
                            existing_history = json.loads(content)
                        except json.JSONDecodeError:
                            # If file is corrupted, repair it
                            self._repair_history_file(history_file)
                            existing_history = {}
            
            # Add or update this email's history
            existing_history[email] = history
            
            # Save updated history
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(existing_history, f, indent=4)
            
            logger.info(f"Saved verification history for {email} to {category} history")
            return True
        except Exception as e:
            logger.error(f"Error saving verification history for {email}: {e}")
            return False