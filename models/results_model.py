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
        
        # Initialize data directory for simple email lists (just email column)
        self.data_dir = "./data"
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Data files with just email column
        self.data_files = {
            VALID: os.path.join(self.data_dir, "Valid.csv"),
            INVALID: os.path.join(self.data_dir, "Invalid.csv"),
            RISKY: os.path.join(self.data_dir, "Risky.csv"),
            CUSTOM: os.path.join(self.data_dir, "Custom.csv"),
        }
        
        # Initialize results directory for detailed verification results
        self.results_dir = "./results"
        os.makedirs(self.results_dir, exist_ok=True)
        
        # Results files with all details
        self.results_files = {
            VALID: os.path.join(self.results_dir, "Valid_Results.csv"),
            INVALID: os.path.join(self.results_dir, "Invalid_Results.csv"),
            RISKY: os.path.join(self.results_dir, "Risky_Results.csv"),
            CUSTOM: os.path.join(self.results_dir, "Custom_Results.csv"),
        }
        
        # Create history directory for tracking verification history
        self.history_dir = os.path.join("./statistics", "history")
        os.makedirs(self.history_dir, exist_ok=True)
        
        # Ensure data files exist (with no headers, just emails)
        for category, file_path in self.data_files.items():
            if not os.path.exists(file_path):
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    pass  # Create empty file, no headers
        
        # Ensure results files exist with headers
        for category, file_path in self.results_files.items():
            if not os.path.exists(file_path):
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Email", "Provider", "Timestamp", "Reason", "Details"])
        
        # Ensure history JSON files exist
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
                if os.path.exists(self.data_files[category]):
                    with open(self.data_files[category], 'r', newline='', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        if any(row and row[0] == email for row in reader):
                            return True, category
            except Exception as e:
                logger.error(f"Error checking {category}.csv: {e}")
        
        return False, None
    
    def save_result(self, result: EmailVerificationResult) -> None:
        """
        Save verification result to the appropriate files.
        
        Args:
            result: The verification result to save
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Convert details to string if present
        details_str = str(result.details) if result.details else ""
        
        # First check if email already exists in any data file
        exists, existing_category = self.check_email_in_data(result.email)
        
        # If it exists in a different category, log this but continue
        if exists and existing_category != result.category:
            logger.info(f"{result.email} already exists in {existing_category} list but is now being saved as {result.category}")
        
        # Save to results file (with all details)
        results_file_path = self.results_files[result.category]
        results_exists = False
        
        try:
            if os.path.exists(results_file_path):
                with open(results_file_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    results_exists = any(row and row[0] == result.email for row in reader)
        except Exception as e:
            logger.error(f"Error checking if email exists in {result.category} results: {e}")
        
        if not results_exists:
            with open(results_file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([result.email, result.provider, timestamp, result.reason, details_str])
            
            logger.info(f"Saved {result.email} to {result.category} results")
        
        # Only save to data file if it doesn't already exist in any category
        if not exists:
            self.add_email_to_data(result.email, result.category)
    
    def add_email_to_data(self, email: str, category: str) -> bool:
        """
        Add an email to the appropriate data file (just email column).
        
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
            data_file_path = self.data_files[category]
            
            # Check if email already exists in the file
            exists = False
            try:
                if os.path.exists(data_file_path):
                    with open(data_file_path, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        exists = any(row and row[0] == email for row in reader)
            except Exception as e:
                logger.error(f"Error checking if email exists in {category} data: {e}")
            
            if not exists:
                # Save ONLY the email to the data file (no other columns)
                with open(data_file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([email])
                
                logger.info(f"Added {email} to {category} data")
                return True
            else:
                logger.info(f"{email} already exists in {category} data")
                return True
        except Exception as e:
            logger.error(f"Error adding email to {category} data: {e}")
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
                try:
                    with open(temp_history_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            temp_history = json.loads(content)
                except json.JSONDecodeError as je:
                    logger.error(f"JSON parsing error in temp history file: {je}")
                    # Attempt to repair the file
                    self._repair_temp_history_file(temp_history_file)
                    # Try loading again after repair
                    try:
                        with open(temp_history_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:
                                temp_history = json.loads(content)
                    except:
                        # If still failing, start with empty dict
                        temp_history = {}
            
            # Add or update this email's history
            if email not in temp_history:
                temp_history[email] = []
            
            temp_history[email].append(event_entry)
            
            # Save updated history
            with open(temp_history_file, 'w', encoding='utf-8') as f:
                json.dump(temp_history, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving history event for {email}: {e}")
            # As a last resort, try to create a new file with just this email's history
            try:
                with open(temp_history_file, 'w', encoding='utf-8') as f:
                    json.dump({email: [event_entry]}, f, indent=4)
            except Exception as e2:
                logger.error(f"Failed to create new history file: {e2}")
    
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
                try:
                    with open(history_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            existing_history = json.loads(content)
                except json.JSONDecodeError as je:
                    logger.error(f"JSON parsing error in {category} history file: {je}")
                    # Try to repair the file
                    self._repair_history_file(history_file)
                    # Try loading again after repair
                    try:
                        with open(history_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:
                                existing_history = json.loads(content)
                    except:
                        # If still failing, start with empty dict
                        existing_history = {}
            
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
                        content = f.read().strip()
                        if content:
                            temp_history = json.loads(content)
                        else:
                            temp_history = {}
                    
                    if email in temp_history:
                        # Remove this email from temp history
                        del temp_history[email]
                        
                        # Save updated temp history
                        with open(temp_history_file, 'w', encoding='utf-8') as f:
                            json.dump(temp_history, f, indent=4)
                except json.JSONDecodeError as je:
                    logger.error(f"JSON parsing error in temp history file: {je}")
                    # Attempt to repair the file with a clean structure
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
        
        # Count from data files
        for category, file_path in self.data_files.items():
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        counts[category] = sum(1 for row in csv.reader(f) if row)
                except Exception as e:
                    logger.error(f"Error counting results in {category}.csv: {e}")
        
        return counts