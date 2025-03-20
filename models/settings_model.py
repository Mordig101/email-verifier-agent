import os
import csv
import json
import logging
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Dict, List, Any, Optional, Union, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class SettingsModel:
    """Model for managing application settings."""
    
    def __init__(self, settings_file: str = "settings/settings.csv"):
        """
        Initialize the settings manager.
        
        Args:
            settings_file: Path to the settings CSV file
        """
        self.settings_file = settings_file
        self.settings: Dict[str, Dict[str, Any]] = {}
        self._ensure_settings_file()
        self._ensure_data_folders()
        self.load_settings()
        
        # Initialize encryption key
        self._init_encryption()
    
    def _init_encryption(self) -> None:
        """Initialize encryption for sensitive data."""
        key_file = os.path.join(os.path.dirname(self.settings_file), "encryption.key")
        
        if not os.path.exists(key_file):
            # Generate a new key
            salt = os.urandom(16)
            # Use a default password, in production this should be more secure
            password = b"email_verifier_default_password"
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password))
            
            # Save the key and salt
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)
            
            salt_file = os.path.join(os.path.dirname(self.settings_file), "salt.bin")
            with open(salt_file, 'wb') as f:
                f.write(salt)
        else:
            # Load existing key
            with open(key_file, 'rb') as f:
                key = f.read()
        
        self.cipher_suite = Fernet(key)
    
    def _encrypt(self, data: str) -> str:
        """
        Encrypt sensitive data.
        
        Args:
            data: The data to encrypt
            
        Returns:
            str: The encrypted data as a base64 string
        """
        if not data:
            return ""
        
        encrypted = self.cipher_suite.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    def _decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt sensitive data.
        
        Args:
            encrypted_data: The encrypted data as a base64 string
            
        Returns:
            str: The decrypted data
        """
        if not encrypted_data:
            return ""
        
        try:
            decoded = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted = self.cipher_suite.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Error decrypting data: {e}")
            return ""
    
    def _ensure_settings_file(self) -> None:
        """Ensure the settings directory and file exist."""
        os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
        
        # Create settings file with default values if it doesn't exist
        if not os.path.exists(self.settings_file):
            default_settings = [
                # Feature, Value, Enabled
                ["proxy_enabled", "False", "False"],
                ["proxy_list", "", "False"],
                ["screenshot_location", "./screenshots", "True"],
                ["screenshot_mode", "problems", "True"],
                ["smtp_accounts", "", "False"],
                ["user_agent_rotation", "True", "True"],
                ["microsoft_api", "True", "True"],
                ["catch_all_detection", "True", "True"],
                # Multi-terminal support
                ["multi_terminal_enabled", "False", "False"],
                ["terminal_count", "2", "False"],
                ["real_multiple_terminals", "False", "False"],
                # Verification loop
                ["verification_loop_enabled", "True", "True"],
                # Browser selection
                ["browsers", "chrome,edge,firefox", "True"],
                # Browser wait time
                ["browser_wait_time", "3", "True"],
                # Browser display
                ["browser_headless", "False", "False"],
                # Rate limiting
                ["rate_limit_enabled", "True", "True"],
                ["rate_limit_max_requests", "10", "True"],
                ["rate_limit_time_window", "60", "True"],
                # Security
                ["secure_credentials", "True", "True"],
                # Logging
                ["log_level", "INFO", "True"],
                ["log_to_file", "True", "True"],
                ["log_file", "./email_verifier.log", "True"]
            ]
            
            with open(self.settings_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["feature", "value", "enabled"])
                for setting in default_settings:
                    writer.writerow(setting)
    
    def _ensure_data_folders(self) -> None:
        """Ensure the data folders and files exist."""
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
        
        # Create statistics directory
        stats_dir = "./statistics"
        os.makedirs(stats_dir, exist_ok=True)
        
        # Create history directory
        history_dir = os.path.join(stats_dir, "history")
        os.makedirs(history_dir, exist_ok=True)
        
        # Create history files if they don't exist
        for category in ["valid", "invalid", "risky", "custom"]:
            history_file = os.path.join(history_dir, f"{category}.json")
            if not os.path.exists(history_file):
                with open(history_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=4)
        
        # Create temp history file
        temp_history_file = os.path.join(history_dir, "temp_history.json")
        if not os.path.exists(temp_history_file):
            with open(temp_history_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, indent=4)
    
    def load_settings(self) -> None:
        """Load settings from the CSV file."""
        try:
            with open(self.settings_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.settings[row["feature"]] = {
                        "value": row["value"],
                        "enabled": row["enabled"].lower() == "true"
                    }
            logger.info(f"Settings loaded from {self.settings_file}")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            # Use default settings if loading fails
            self.settings = {
                "proxy_enabled": {"value": "False", "enabled": False},
                "proxy_list": {"value": "", "enabled": False},
                "screenshot_location": {"value": "./screenshots", "enabled": True},
                "screenshot_mode": {"value": "problems", "enabled": True},
                "smtp_accounts": {"value": "", "enabled": False},
                "user_agent_rotation": {"value": "True", "enabled": True},
                "microsoft_api": {"value": "True", "enabled": True},
                "catch_all_detection": {"value": "True", "enabled": True},
                "multi_terminal_enabled": {"value": "False", "enabled": False},
                "terminal_count": {"value": "2", "enabled": False},
                "real_multiple_terminals": {"value": "False", "enabled": False},
                "verification_loop_enabled": {"value": "True", "enabled": True},
                "browsers": {"value": "chrome,edge,firefox", "enabled": True},
                "browser_wait_time": {"value": "3", "enabled": True},
                "browser_headless": {"value": "False", "enabled": False},
                "rate_limit_enabled": {"value": "True", "enabled": True},
                "rate_limit_max_requests": {"value": "10", "enabled": True},
                "rate_limit_time_window": {"value": "60", "enabled": True},
                "secure_credentials": {"value": "True", "enabled": True},
                "log_level": {"value": "INFO", "enabled": True},
                "log_to_file": {"value": "True", "enabled": True},
                "log_file": {"value": "./email_verifier.log", "enabled": True}
            }
    
    def save_settings(self) -> bool:
        """
        Save current settings to the CSV file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(self.settings_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["feature", "value", "enabled"])
                for feature, data in self.settings.items():
                    writer.writerow([feature, data["value"], str(data["enabled"])])
            logger.info(f"Settings saved to {self.settings_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False
    
    def get(self, feature: str, default: Any = None) -> Any:
        """
        Get a setting value if it exists and is enabled.
        
        Args:
            feature: The feature name
            default: Default value if feature not found or disabled
            
        Returns:
            Any: The setting value or default
        """
        if feature in self.settings and self.settings[feature]["enabled"]:
            return self.settings[feature]["value"]
        return default
    
    def is_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled.
        
        Args:
            feature: The feature name
            
        Returns:
            bool: True if enabled, False otherwise
        """
        return feature in self.settings and self.settings[feature]["enabled"]
    
    def set(self, feature: str, value: str, enabled: bool = True) -> bool:
        """
        Set a setting value and enabled status.
        
        Args:
            feature: The feature name
            value: The feature value
            enabled: Whether the feature is enabled
            
        Returns:
            bool: True if successful, False otherwise
        """
        self.settings[feature] = {
            "value": value,
            "enabled": enabled
        }
        return self.save_settings()
    
    def get_smtp_accounts(self) -> List[Dict[str, Any]]:
        """
        Get the list of SMTP accounts for verification.
        
        Returns:
            List[Dict[str, Any]]: List of SMTP account dictionaries
        """
        accounts_str = self.get("smtp_accounts", "")
        if not accounts_str:
            return []
        
        accounts = []
        for account_str in accounts_str.split("|"):
            parts = account_str.split(",")
            if len(parts) == 6:  # Make sure we have all 6 parts
                # Decrypt password if secure credentials is enabled
                password = parts[5]
                if self.is_enabled("secure_credentials"):
                    password = self._decrypt(password)
                
                accounts.append({
                    "smtp_server": parts[0],
                    "smtp_port": int(parts[1]),
                    "imap_server": parts[2],
                    "imap_port": int(parts[3]),
                    "email": parts[4],
                    "password": password
                })
        return accounts
    
    def add_smtp_account(self, smtp_server: str, smtp_port: int, imap_server: str, 
                         imap_port: int, email: str, password: str) -> bool:
        """
        Add an SMTP account for verification.
        
        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port
            imap_server: IMAP server hostname
            imap_port: IMAP server port
            email: Email address
            password: Password
            
        Returns:
            bool: True if successful, False otherwise
        """
        accounts = self.get_smtp_accounts()
        
        # Check if account already exists
        for account in accounts:
            if account["email"] == email:
                return False
        
        # Encrypt password if secure credentials is enabled
        if self.is_enabled("secure_credentials"):
            password = self._encrypt(password)
        
        # Add the new account
        accounts_str = self.get("smtp_accounts", "")
        if accounts_str:
            accounts_str += "|"
        
        accounts_str += f"{smtp_server},{smtp_port},{imap_server},{imap_port},{email},{password}"
        return self.set("smtp_accounts", accounts_str, True)
    
    def get_proxies(self) -> List[str]:
        """
        Get the list of proxies.
        
        Returns:
            List[str]: List of proxy strings
        """
        proxies_str = self.get("proxy_list", "")
        if not proxies_str:
            return []
        
        return [proxy.strip() for proxy in proxies_str.split("|") if proxy.strip()]
    
    def add_proxy(self, proxy: str) -> bool:
        """
        Add a proxy to the list.
        
        Args:
            proxy: The proxy string (host:port)
            
        Returns:
            bool: True if successful, False otherwise
        """
        proxies = self.get_proxies()
        
        # Check if proxy already exists
        if proxy in proxies:
            return False
        
        # Add the new proxy
        proxies_str = self.get("proxy_list", "")
        if proxies_str:
            proxies_str += "|"
        
        proxies_str += proxy
        return self.set("proxy_list", proxies_str, True)
    
    def get_browsers(self) -> List[str]:
        """
        Get the list of browsers to use.
        
        Returns:
            List[str]: List of browser names
        """
        browsers_str = self.get("browsers", "chrome")
        return [browser.strip() for browser in browsers_str.split(",") if browser.strip()]
    
    def get_browser_wait_time(self) -> int:
        """
        Get the browser wait time in seconds.
        
        Returns:
            int: Wait time in seconds
        """
        try:
            return int(self.get("browser_wait_time", "3"))
        except ValueError:
            return 3
    
    def get_terminal_count(self) -> int:
        """
        Get the number of terminals to use for multi-terminal support.
        
        Returns:
            int: Number of terminals
        """
        try:
            return int(self.get("terminal_count", "2"))
        except ValueError:
            return 2
    
    def get_rate_limit_settings(self) -> Tuple[int, int]:
        """
        Get rate limit settings.
        
        Returns:
            Tuple[int, int]: (max_requests, time_window)
        """
        try:
            max_requests = int(self.get("rate_limit_max_requests", "10"))
            time_window = int(self.get("rate_limit_time_window", "60"))
            return max_requests, time_window
        except ValueError:
            return 10, 60
    
    def get_blacklisted_domains(self) -> List[str]:
        """
        Get the list of blacklisted domains.
        
        Returns:
            List[str]: List of blacklisted domains
        """
        try:
            with open("./data/D-blacklist.csv", 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return [row["domain"] for row in reader]
        except Exception as e:
            logger.error(f"Error loading blacklisted domains: {e}")
            return []
    
    def get_whitelisted_domains(self) -> List[str]:
        """
        Get the list of whitelisted domains.
        
        Returns:
            List[str]: List of whitelisted domains
        """
        try:
            with open("./data/D-WhiteList.csv", 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return [row["domain"] for row in reader]
        except Exception as e:
            logger.error(f"Error loading whitelisted domains: {e}")
            return []
    
    def save_verification_statistics(self, verification_name: str, statistics: Dict[str, Any]) -> bool:
        """
        Save verification statistics to a JSON file.
        
        Args:
            verification_name: Name of the verification
            statistics: Statistics dictionary
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            stats_dir = "./statistics"
            os.makedirs(stats_dir, exist_ok=True)
            
            file_path = os.path.join(stats_dir, f"{verification_name}.json")
            
            # Add timestamp to statistics
            statistics["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(statistics, f, indent=4)
            
            logger.info(f"Statistics saved to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving statistics: {e}")
            return False
    
    def get_verification_names(self) -> List[str]:
        """
        Get the list of verification names from the statistics directory.
        
        Returns:
            List[str]: List of verification names
        """
        try:
            stats_dir = "./statistics"
            if not os.path.exists(stats_dir):
                return []
            
            return [os.path.splitext(file)[0] for file in os.listdir(stats_dir) 
                   if file.endswith(".json") and not file.startswith("history_")]
        except Exception as e:
            logger.error(f"Error getting verification names: {e}")
            return []
    
    def get_verification_statistics(self, verification_name: str) -> Optional[Dict[str, Any]]:
        """
        Get verification statistics from a JSON file.
        
        Args:
            verification_name: Name of the verification
            
        Returns:
            Optional[Dict[str, Any]]: Statistics dictionary or None if not found
        """
        try:
            file_path = f"./statistics/{verification_name}.json"
            
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading statistics: {e}")
            return None
    
    def configure_multi_terminal_settings(self) -> None:
        """Configure multi-terminal settings."""
        print("\nMulti-terminal Settings:")
        current_enabled = self.is_enabled("multi_terminal_enabled")
        current_count = self.get("terminal_count", "2")
        current_real = self.is_enabled("real_multiple_terminals")
        
        print(f"Multi-terminal is currently {'enabled' if current_enabled else 'disabled'}")
        print(f"Current terminal count: {current_count}")
        print(f"Real multiple terminals: {'enabled' if current_real else 'disabled'}")
        
        enable = input("\nEnable multi-terminal? (y/n): ")
        if enable.lower() == 'y':
            count = input("Enter number of terminals (1-8): ")
            try:
                count = min(max(1, int(count)), 8)
            except ValueError:
                count = 2
            
            self.set("multi_terminal_enabled", "True", True)
            self.set("terminal_count", str(count), True)
            
            real = input("Use real multiple terminals? (y/n): ")
            if real.lower() == 'y':
                self.set("real_multiple_terminals", "True", True)
                print("\nUsing real multiple terminals (recommended limit: 4 terminals)")
            else:
                self.set("real_multiple_terminals", "False", False)
            
            print(f"\nMulti-terminal enabled with {count} terminals")
        else:
            self.set("multi_terminal_enabled", "False", False)
            print("\nMulti-terminal disabled")
    
    def configure_browser_settings(self) -> None:
        """Configure browser settings."""
        print("\nBrowser Settings:")
        current_browsers = self.get("browsers", "chrome")
        current_wait_time = self.get("browser_wait_time", "3")
        current_headless = self.is_enabled("browser_headless")
        
        print(f"Current browsers: {current_browsers}")
        print(f"Current browser wait time: {current_wait_time} seconds")
        print(f"Headless mode: {'enabled' if current_headless else 'disabled'}")
        
        browsers = input("\nEnter browsers to use (comma-separated, e.g., chrome,edge,firefox): ")
        if browsers:
            self.set("browsers", browsers, True)
        
        wait_time = input("Enter browser wait time in seconds: ")
        try:
            wait_time = max(1, int(wait_time))
            self.set("browser_wait_time", str(wait_time), True)
        except ValueError:
            pass
        
        headless = input("Enable headless mode (browser runs in background)? (y/n): ")
        if headless.lower() == 'y':
            self.set("browser_headless", "True", True)
        else:
            self.set("browser_headless", "False", False)
        
        print("\nBrowser settings updated")
    
    def configure_domain_lists(self) -> None:
        """Configure domain lists."""
        print("\nDomain Lists:")
        print("1. View blacklisted domains")
        print("2. Add domain to blacklist")
        print("3. View whitelisted domains")
        print("4. Add domain to whitelist")
        
        domain_choice = input("\nEnter your choice (1-4): ")
        
        if domain_choice == "1":
            # View blacklisted domains
            blacklisted = self.get_blacklisted_domains()
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
            whitelisted = self.get_whitelisted_domains()
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
    
    def configure_smtp_accounts(self) -> None:
        """Configure SMTP accounts."""
        print("\nSMTP Accounts:")
        accounts = self.get_smtp_accounts()
        
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
                
                self.add_smtp_account(
                    smtp_server, smtp_port, imap_server, imap_port, email_address, password
                )
                print("\nSMTP account added successfully")
            except ValueError:
                print("\nInvalid port number")
    
    def configure_proxy_settings(self) -> None:
        """Configure proxy settings."""
        print("\nProxy Settings:")
        current_enabled = self.is_enabled("proxy_enabled")
        current_proxies = self.get_proxies()
        
        print(f"Proxy is currently {'enabled' if current_enabled else 'disabled'}")
        if current_proxies:
            print("\nConfigured proxies:")
            for i, proxy in enumerate(current_proxies, 1):
                print(f"{i}. {proxy}")
        else:
            print("No proxies configured")
        
        enable = input("\nEnable proxy? (y/n): ")
        if enable.lower() == 'y':
            self.set("proxy_enabled", "True", True)
            
            add_proxy = input("Add a new proxy? (y/n): ")
            if add_proxy.lower() == 'y':
                proxy = input("Enter proxy (format: host:port): ")
                if proxy:
                    self.add_proxy(proxy)
                    print(f"\nProxy {proxy} added")
        else:
            self.set("proxy_enabled", "False", False)
            print("\nProxy disabled")
    
    def configure_screenshot_settings(self) -> None:
        """Configure screenshot settings."""
        print("\nScreenshot Settings:")
        current_mode = self.get("screenshot_mode", "problems")
        current_location = self.get("screenshot_location", "./screenshots")
        
        print(f"Current screenshot mode: {current_mode}")
        print(f"Current screenshot location: {current_location}")
        
        print("\nScreenshot modes:")
        print("1. none - Don't take screenshots")
        print("2. problems - Only take screenshots for risky or error stages")
        print("3. steps - Take screenshots at key verification steps")
        print("4. all - Take screenshots at every stage")
        
        mode_choice = input("\nEnter your choice (1-4): ")
        
        if mode_choice == "1":
            self.set("screenshot_mode", "none", True)
            print("\nScreenshot mode set to 'none'")
        elif mode_choice == "2":
            self.set("screenshot_mode", "problems", True)
            print("\nScreenshot mode set to 'problems'")
        elif mode_choice == "3":
            self.set("screenshot_mode", "steps", True)
            print("\nScreenshot mode set to 'steps'")
        elif mode_choice == "4":
            self.set("screenshot_mode", "all", True)
            print("\nScreenshot mode set to 'all'")
        
        location = input("\nEnter screenshot location (default: ./screenshots): ")
        if location:
            self.set("screenshot_location", location, True)
            os.makedirs(location, exist_ok=True)
            print(f"\nScreenshot location set to '{location}'")
    
    def configure_rate_limiting_settings(self) -> None:
        """Configure rate limiting settings."""
        print("\nRate Limiting Settings:")
        current_max_requests = self.get("rate_limit_max_requests", "10")
        current_time_window = self.get("rate_limit_time_window", "60")
        
        print(f"Current max requests per time window: {current_max_requests}")
        print(f"Current time window (seconds): {current_time_window}")
        
        max_requests = input("\nEnter max requests per time window: ")
        if max_requests:
            try:
                max_requests = max(1, int(max_requests))
                self.set("rate_limit_max_requests", str(max_requests), True)
            except ValueError:
                pass
        
        time_window = input("Enter time window in seconds: ")
        if time_window:
            try:
                time_window = max(1, int(time_window))
                self.set("rate_limit_time_window", str(time_window), True)
            except ValueError:
                pass
        
        print("\nRate limiting settings updated")
