import os
import csv
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class ResultsModel:
    """Model for storing and retrieving verification results."""
    
    def __init__(self, settings_model):
        """
        Initialize the results model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Initialize CSV files
        self.data_dir = "./data"
        self.csv_files = {
            VALID: os.path.join(self.data_dir, "Valid.csv"),
            INVALID: os.path.join(self.data_dir, "Invalid.csv"),
            RISKY: os.path.join(self.data_dir, "Risky.csv"),
            CUSTOM: os.path.join(self.data_dir, "Custom.csv"),
        }
        
        # Create history directory for tracking verification history
        self.history_dir = os.path.join("./statistics", "history")
        os.makedirs(self.history_dir, exist_ok=True)
    
    def check_email_in_data(self, email: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an email exists in any of the data files.
        
        Args:
            email: The email address to check
            
        Returns:
            Tuple[bool, Optional[str]]: (exists, category)
        """
        categories = [VALID, INVALID, RISKY, CUSTOM]
        
        for category in categories:
            try:
                with open(self.csv_files[category], 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Skip header
                    if any(row[0] == email for row in reader):
                        return True, category
            except Exception as e:
                logger.error(f"Error checking {category}.csv: {e}")
        
        return False, None
    
    def save_result(self, result: EmailVerificationResult) -> None:
        """
        Save verification result to the appropriate CSV file.
        
        Args:
            result: The verification result to save
        """
        file_path = self.csv_files[result.category]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Convert details to string if present
        details_str = str(result.details) if result.details else ""
        
        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([result.email, result.provider, timestamp, result.reason, details_str])
        
        # Also save to the data folder
        self.add_email_to_data(result.email, result.category)
        
        logger.info(f"Saved {result.email} to {result.category} list")
    
    def add_email_to_data(self, email: str, category: str) -> bool:
        """
        Add an email to the appropriate data file.
        
        Args:
            email: The email address to add
            category: The category (valid, invalid, risky, custom)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if category.lower() not in [VALID, INVALID, RISKY, CUSTOM]:
            logger.error(f"Invalid category: {category}")
            return False
        
        try:
            file_path = self.csv_files[category]
            
            # Check if email already exists in the file
            exists = False
            try:
                with open(file_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Skip header
                    exists = any(row[0] == email for row in reader)
            except Exception:
                pass
            
            if not exists:
                with open(file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([email])
                
                logger.info(f"Added {email} to {category} list")
                return True
            else:
                logger.info(f"{email} already exists in {category} list")
                return True
        except Exception as e:
            logger.error(f"Error adding email to {category} list: {e}")
            return False
    
    def save_history_event(self, email: str, event_entry: Dict[str, str]) -> None:
        """
        Save a history event to disk immediately.
        
        Args:
            email: The email address
            event_entry: The event entry to save
        """
        # We don't know the category yet, so we'll save to a temporary file
        temp_history_file = os.path.join(self.history_dir, "temp_history.json")
        
        try:
            # Load existing temp history
            temp_history = {}
            if os.path.exists(temp_history_file):
                with open(temp_history_file, 'r', encoding='utf-8') as f:
                    temp_history = json.load(f)
            
            # Add or update this email's history
            if email not in temp_history:
                temp_history[email] = []
            
            temp_history[email].append(event_entry)
            
            # Save updated history
            with open(temp_history_file, 'w', encoding='utf-8') as f:
                json.dump(temp_history, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving history event for {email}: {e}")
    
    def save_history(self, email: str, category: str, history: List[Dict[str, str]]) -> None:
        """
        Save the verification history for an email to the appropriate JSON file.
        
        Args:
            email: The email address
            category: The verification category (valid, invalid, risky, custom)
            history: The verification history
        """
        history_file = os.path.join(self.history_dir, f"{category}.json")
        
        try:
            # Load existing history
            existing_history = {}
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    existing_history = json.load(f)
            
            # Add or update this email's history
            existing_history[email] = history
            
            # Save updated history
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(existing_history, f, indent=4)
                
            logger.info(f"Saved verification history for {email} to {category} history")
            
            # Also move from temp history to permanent history
            self._move_from_temp_history(email)
        except Exception as e:
            logger.error(f"Error saving verification history for {email}: {e}")
    
    def _move_from_temp_history(self, email: str) -> None:
        """
        Move email history from temporary history file to permanent history file.
        
        Args:
            email: The email address to move history for
        """
        temp_history_file = os.path.join(self.history_dir, "temp_history.json")
        
        try:
            if os.path.exists(temp_history_file):
                try:
                    with open(temp_history_file, 'r', encoding='utf-8') as f:
                        temp_history = json.load(f)
                    
                    if email in temp_history:
                        # Remove this email from temp history
                        del temp_history[email]
                        
                        # Save updated temp history
                        with open(temp_history_file, 'w', encoding='utf-8') as f:
                            json.dump(temp_history, f, indent=4)
                except json.JSONDecodeError as je:
                    logger.error(f"JSON parsing error in temp history file: {je}")
                    # Attempt to recover the file with a clean structure
                    self._repair_temp_history_file(temp_history_file, email)
        except Exception as e:
            logger.error(f"Error moving {email} from temp history: {e}")

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
    
    def get_results_summary(self) -> Dict[str, int]:
        """
        Get a summary of verification results.
        
        Returns:
            Dict[str, int]: Dictionary of category counts
        """
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