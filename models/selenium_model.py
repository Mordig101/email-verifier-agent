import os
import time
import random
import logging
from typing import Dict, List, Any, Optional, Tuple
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException, 
    StaleElementReferenceException, ElementClickInterceptedException, 
    ElementNotInteractableException
)
from contextlib import contextmanager
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class SeleniumModel:
    """Model for Selenium-based email verification."""
    
    def __init__(self, settings_model):
        """
        Initialize the Selenium model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Rate limiter will be initialized by the controller
        self.rate_limiter = None
        
        # Initialize browser options
        self._init_browser_options()
        
        # Error messages that indicate an email doesn't exist
        self.nonexistent_email_phrases = {
            # Google
            'gmail.com': [
                "couldn't find your google account",
                "couldn't find your account",
                "no account found with that email",
                "couldn't find an account with that email",
                "Impossible de trouver votre compte Google"
            ],
            # Microsoft
            'outlook.com': [
                "we couldn't find an account with that username",
                "that microsoft account doesn't exist",
                "no account found",
                "this username may be incorrect",
                "ce nom d'utilisateur est peut-être incorrect"
            ],
            # Yahoo
            'yahoo.com': [
                "we couldn't find this account",
                "we don't recognize this email",
                "no account exists with this email address",
                "désolé, nous ne reconnaissons pas cette adresse mail"
            ],
            # Generic phrases that many providers use
            'generic': [
                "email not found",
                "user not found",
                "account not found",
                "no account",
                "doesn't exist",
                "invalid email",
                "email address is incorrect"
            ]
        }
        
        # Google-specific URL patterns for different states
        self.google_url_patterns = {
            'identifier': '/signin/identifier',  # Initial login page
            'pwd_challenge': '/signin/challenge/pwd',  # Password page (valid email)
            'rejected': '/signin/rejected',  # Security issue or rate limiting, not necessarily invalid
            'captcha': '/signin/v2/challenge/ipp',  # CAPTCHA challenge
            'security_challenge': '/signin/challenge',  # Other security challenges
            'TwoAcount': 'signin/shadowdisambiguate?'  # Multiple accounts for the same email
        }
        
        # Provider-specific page changes that indicate valid emails
        self.valid_email_indicators = {
            'gmail.com': {
                'heading_changes': {
                    'before': ['Sign in'],
                    'after': ['Welcome']
                },
                'url_patterns': {
                    'before': '/signin/identifier',
                    'after': '/signin/challenge/pwd'
                }
            },
            'outlook.com': {
                'heading_changes': {
                    'before': ['Sign in', 'Se connecter'],
                    'after': ['Enter password', 'Entrez le mot de passe']
                }
            },
            # Adding Yahoo URL patterns
            'yahoo.com': {
                'url_patterns': {
                    'before': 'https://login.yahoo.com/',
                    'after': 'https://login.yahoo.com/account/challenge/recaptcha'
                }
            }
        }
        
        # Next button text in different languages
        self.next_button_texts = [
            "Next", "Suivant", "Continuer", "Continue", "Weiter", 
            "Siguiente", "Próximo", "Avanti", "Volgende", "Далее",
            "下一步", "次へ", "다음", "التالي", "Tiếp theo"
        ]
        
        # Microsoft multi-account text indicators
        self.microsoft_multi_account_phrases = [
            "Il semble que cet e-mail est utilisé avec plus d'un compte Microsoft",
            "Il semble que ce courriel est utilisé avec plus d'un compte Microsoft",
            "Nous rencontrons des problèmes pour localiser votre compte",
            "This email is used with more than one account",
            "We're having trouble locating your account",
            "Lequel souhaitez-vous utiliser"
        ]
        
        # Google specific XPath for error detection
        self.google_error_xpath = "/html/body/div[1]/div[1]/div[2]/c-wiz/div/div[2]/div/div/div[1]/form/span/section/div/div/div[1]/div/div[2]"
        
        # Yahoo specific error element
        self.yahoo_error_selector = "p#username-error.error-msg"
        
        # Microsoft multi-account element
        self.microsoft_multi_account_xpath = "//*[@id=\"loginDescription\"]"
    
    def set_rate_limiter(self, rate_limiter):
        """
        Set the rate limiter.
        
        Args:
            rate_limiter: The rate limiter instance
        """
        self.rate_limiter = rate_limiter
    
    def _init_browser_options(self) -> None:
        """Initialize browser options for different browsers."""
        # Chrome options
        self.chrome_options = ChromeOptions()
        self.chrome_options.add_argument("--incognito")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option("useAutomationExtension", False)
        
        # Add headless option if enabled
        if self.settings_model.is_enabled("browser_headless"):
            self.chrome_options.add_argument("--headless=new")
            
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "autofill.profile_enabled": False,
            "autofill.credit_card_enabled": False
        }
        self.chrome_options.add_experimental_option("prefs", prefs)
        
        # Edge options
        self.edge_options = EdgeOptions()
        self.edge_options.add_argument("--incognito")
        self.edge_options.add_argument("--no-sandbox")
        self.edge_options.add_argument("--disable-dev-shm-usage")
        self.edge_options.add_argument("--disable-gpu")
        self.edge_options.add_argument("--window-size=1920,1080")
        self.edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.edge_options.add_experimental_option("useAutomationExtension", False)
        self.edge_options.add_experimental_option("prefs", prefs)
        
        # Add headless option if enabled
        if self.settings_model.is_enabled("browser_headless"):
            self.edge_options.add_argument("--headless=new")
        
        # Firefox options
        self.firefox_options = FirefoxOptions()
        self.firefox_options.add_argument("--private")
        self.firefox_options.add_argument("--no-sandbox")
        self.firefox_options.add_argument("--disable-dev-shm-usage")
        self.firefox_options.add_argument("--width=1920")
        self.firefox_options.add_argument("--height=1080")
        self.firefox_options.set_preference("dom.webnotifications.enabled", False)
        self.firefox_options.set_preference("browser.privatebrowsing.autostart", True)
        
        # Add headless option if enabled
        if self.settings_model.is_enabled("browser_headless"):
            self.firefox_options.add_argument("--headless")
    
    @contextmanager
    def _browser_context(self, browser_type: str):
        """
        Context manager for browser instances to ensure proper cleanup.
        
        Args:
            browser_type: The type of browser to use
            
        Yields:
            WebDriver: The browser driver instance
        """
        driver = None
        try:
            driver = self._get_browser_driver(browser_type)
            yield driver
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.error(f"Error closing browser: {e}")
    
    def _get_browser_driver(self, browser_type: str):
        """
        Get a WebDriver instance for the specified browser type.
        
        Args:
            browser_type: The type of browser to use
            
        Returns:
            WebDriver: The browser driver instance
        """
        browser_type = browser_type.lower()
        
        if browser_type == "chrome":
            try:
                # Use undetected-chromedriver by default
                options = uc.ChromeOptions()
                options.add_argument("--incognito")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")
                
                # Add headless option if enabled
                if self.settings_model.is_enabled("browser_headless"):
                    options.add_argument("--headless=new")
                
                # Add proxy if enabled
                if self.settings_model.is_enabled("proxy_enabled"):
                    proxies = self.settings_model.get_proxies()
                    if proxies:
                        proxy = random.choice(proxies)
                        options.add_argument(f'--proxy-server={proxy}')
                
                return uc.Chrome(options=options)
            except Exception as e:
                logger.error(f"Error creating undetected Chrome driver: {e}")
                logger.info("Falling back to regular Chrome driver")
                
                # Fall back to regular Chrome driver
                return webdriver.Chrome(options=self.chrome_options)
        
        elif browser_type == "edge":
            # Add proxy if enabled
            if self.settings_model.is_enabled("proxy_enabled"):
                proxies = self.settings_model.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    self.edge_options.add_argument(f'--proxy-server={proxy}')
            
            return webdriver.Edge(options=self.edge_options)
        
        elif browser_type == "firefox":
            # Add proxy if enabled
            if self.settings_model.is_enabled("proxy_enabled"):
                proxies = self.settings_model.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    proxy_parts = proxy.split(":")
                    if len(proxy_parts) == 2:
                        host, port = proxy_parts
                        self.firefox_options.set_preference("network.proxy.type", 1)
                        self.firefox_options.set_preference("network.proxy.http", host)
                        self.firefox_options.set_preference("network.proxy.http_port", int(port))
                        self.firefox_options.set_preference("network.proxy.ssl", host)
                        self.firefox_options.set_preference("network.proxy.ssl_port", int(port))
            
            return webdriver.Firefox(options=self.firefox_options)
        
        else:
            # Default to undetected Chrome
            logger.warning(f"Unknown browser type: {browser_type}, defaulting to undetected Chrome")
            try:
                options = uc.ChromeOptions()
                options.add_argument("--incognito")
                options.add_argument("--no-sandbox")
                
                # Add headless option if enabled
                if self.settings_model.is_enabled("browser_headless"):
                    options.add_argument("--headless=new")
                
                return uc.Chrome(options=options)
            except Exception as e:
                logger.error(f"Error creating undetected Chrome driver: {e}")
                logger.info("Falling back to regular Chrome driver")
                return webdriver.Chrome(options=self.chrome_options)
    
    def take_screenshot(self, driver, email: str, stage: str) -> Optional[str]:
        """
        Take a screenshot at a specific stage of the verification process.
        
        Args:
            driver: The WebDriver instance
            email: The email address being verified
            stage: The verification stage
            
        Returns:
            Optional[str]: The screenshot filename if taken, None otherwise
        """
        # Check screenshot mode
        screenshot_mode = self.settings_model.get("screenshot_mode", "problems")
        
        # If mode is "none", don't take screenshots
        if screenshot_mode == "none":
            return None
            
        # If mode is "problems", only take screenshots for risky or error stages
        if screenshot_mode == "problems" and not any(x in stage for x in ["error", "risky", "failed", "rejected", "unknown"]):
            return None
            
        # If mode is "steps", take screenshots at key steps
        if screenshot_mode == "steps" and not any(x in stage for x in ["before", "after", "error", "risky", "failed"]):
            return None
            
        # Otherwise, take the screenshot
        try:
            screenshots_dir = self.settings_model.get("screenshot_location", "./screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            filename = f"{screenshots_dir}/{email.replace('@', '_at_')}_{stage}.png"
            driver.save_screenshot(filename)
            logger.info(f"Screenshot saved: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            return None
    
    def human_like_typing(self, element, text: str) -> None:
        """
        Type text in a human-like manner with random delays between keystrokes.
        
        Args:
            element: The web element to type into
            text: The text to type
        """
        # Check if human behavior is enabled
        if self.settings_model.is_enabled("human_behavior_enabled"):
            for char in text:
                element.send_keys(char)
                # Random delay between keystrokes (50-200ms)
                time.sleep(random.uniform(0.05, 0.2))
        else:
            # If human behavior is disabled, just type the text directly
            element.send_keys(text)
    
    def human_like_move_and_click(self, driver, element) -> bool:
        """
        Move to an element and click it in a human-like manner.
        
        Args:
            driver: The WebDriver instance
            element: The element to click
            
        Returns:
            bool: True if the click was successful, False otherwise
        """
        try:
            # Check if human behavior is enabled
            if self.settings_model.is_enabled("human_behavior_enabled"):
                # Create action chain
                actions = ActionChains(driver)
                
                # Move to a random position first
                viewport_width = driver.execute_script("return window.innerWidth;")
                viewport_height = driver.execute_script("return window.innerHeight;")
                random_x = random.randint(0, viewport_width)
                random_y = random.randint(0, viewport_height)
                
                # Move to random position, then to element with a slight offset, then click
                actions.move_by_offset(random_x, random_y)
                actions.pause(random.uniform(0.1, 0.3))
                
                # Get element location
                element_x = element.location['x']
                element_y = element.location['y']
                
                # Calculate center of element
                element_width = element.size['width']
                element_height = element.size['height']
                center_x = element_x + element_width / 2
                center_y = element_y + element_height / 2
                
                # Move to element with slight random offset
                offset_x = random.uniform(-5, 5)
                offset_y = random.uniform(-5, 5)
                actions.move_to_element_with_offset(element, offset_x, offset_y)
                actions.pause(random.uniform(0.1, 0.3))
                
                # Click
                actions.click()
                actions.perform()
                
                return True
            else:
                # If human behavior is disabled, just click directly
                element.click()
                return True
        except Exception as e:
            logger.warning(f"Human-like click failed: {e}")
            # Fall back to regular click
            try:
                element.click()
                return True
            except Exception as click_e:
                logger.error(f"Regular click also failed: {click_e}")
                # Last resort: JavaScript click
                try:
                    driver.execute_script("arguments[0].click();", element)
                    return True
                except Exception as js_e:
                    logger.error(f"JavaScript click failed: {js_e}")
                    return False
    
    def find_next_button(self, driver) -> Optional[Any]:
        """
        Find the 'Next' button using multiple strategies.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Optional[Any]: The button element if found, None otherwise
        """
        # Strategy 1: Look for buttons with specific text
        for text in self.next_button_texts:
            try:
                # Try exact text match
                elements = driver.find_elements(By.XPATH, f"//button[contains(text(), '{text}')]")
                if elements:
                    return elements[0]
                
                # Try case-insensitive match
                elements = driver.find_elements(By.XPATH, f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]")
                if elements:
                    return elements[0]
                
                # Try with span inside button
                elements = driver.find_elements(By.XPATH, f"//button//span[contains(text(), '{text}')]/..")
                if elements:
                    return elements[0]
                
                # Try with input buttons
                elements = driver.find_elements(By.XPATH, f"//input[@type='submit' and contains(@value, '{text}')]")
                if elements:
                    return elements[0]
            except Exception:
                continue
        
        # Strategy 2: Look for common button IDs and classes
        for selector in [
            "#identifierNext",  # Google
            "#idSIButton9",     # Microsoft
            "#login-signin",    # Yahoo
            "button[type='submit']",
            "input[type='submit']",
            ".VfPpkd-LgbsSe-OWXEXe-k8QpJ",  # Google's Next button class
            ".win-button.button_primary"     # Microsoft's Next button class
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        
        # Strategy 3: Look for any button or input that might be a submit button
        try:
            # Look for buttons with common attributes
            for attr in ["submit", "login", "next", "continue", "signin"]:
                elements = driver.find_elements(By.CSS_SELECTOR, f"button[id*='{attr}'], button[class*='{attr}'], button[name*='{attr}']")
                if elements:
                    return elements[0]
            
            # Look for any button as a last resort
            elements = driver.find_elements(By.TAG_NAME, "button")
            if elements:
                # Try to find a button that looks like a submit button (e.g., positioned at the bottom)
                for element in elements:
                    if element.is_displayed() and element.is_enabled():
                        return element
        except Exception:
            pass
        
        return None
    
    def find_email_field(self, driver) -> Optional[Any]:
        """
        Find the email input field using multiple strategies.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Optional[Any]: The field element if found, None otherwise
        """
        # Try common selectors for email fields
        for selector in [
            "input[type='email']", 
            "input[name='email']", 
            "input[name='username']", 
            "input[id*='email']", 
            "input[id*='user']",
            "input[id='identifierId']",  # Google
            "input[name='loginfmt']",    # Microsoft
            "input[id='login-username']" # Yahoo
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and elements[0].is_displayed():
                    return elements[0]
            except Exception:
                continue
        
        # Try to find any input field that might accept email
        try:
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for input_field in inputs:
                try:
                    if input_field.is_displayed() and input_field.get_attribute("type") in ["text", "email"]:
                        return input_field
                except StaleElementReferenceException:
                    continue
        except Exception:
            pass
        
        return None
    
    def check_email_input_validity(self, driver, email_field, email: str) -> bool:
        """
        Check if the email input field contains the correct email.
        
        Args:
            driver: The WebDriver instance
            email_field: The email input field element
            email: The expected email address
            
        Returns:
            bool: True if the field contains the correct email, False otherwise
        """
        # Only perform validation if input validation is enabled
        if not self.settings_model.is_enabled("input_validation_enabled"):
            return True
            
        try:
            # Get the current value of the email field
            current_value = email_field.get_attribute("value")
            
            # Check if the field is empty
            if not current_value:
                logger.info(f"Email field is empty, filling with {email}")
                self.human_like_typing(email_field, email)
                return True
                
            # Check if the field contains the correct email
            if current_value.lower() != email.lower():
                logger.info(f"Email field contains incorrect value: {current_value}, expected: {email}")
                # Clear the field and enter the correct email
                email_field.clear()
                self.human_like_typing(email_field, email)
                return True
                
            # Field already contains the correct email
            return True
        except Exception as e:
            logger.error(f"Error checking email input validity: {e}")
            return False
    
    def check_for_google_error(self, driver) -> Tuple[bool, Optional[str]]:
        """
        Check for Google-specific error message using the provided XPath.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Tuple[bool, Optional[str]]: (has_error, error_message)
        """
        try:
            # Check the specific XPath for Google error
            error_div = driver.find_element(By.XPATH, self.google_error_xpath)
            if error_div:
                # Get the HTML content of the error div
                html_content = error_div.get_attribute('innerHTML')
                
                # Check if the HTML contains the error message structure with "Ekjuhf Jj6Lae" class
                # This is the specific HTML structure that appears when an invalid email is entered
                if "Ekjuhf Jj6Lae" in html_content and "Couldn't find your Google Account" in html_content:
                    return True, "Couldn't find your Google Account"
                
                # Check for SVG icon which appears in error messages
                if "<svg aria-hidden=\"true\" class=\"Qk3oof xTjuxe\"" in html_content:
                    return True, "Google account not found (error icon detected)"
                
                # Check for other error messages
                for phrase in self.nonexistent_email_phrases['gmail.com']:
                    if phrase.lower() in html_content.lower():
                        return True, phrase
            
            return False, None
        except NoSuchElementException:
            return False, None
        except Exception as e:
            logger.error(f"Error checking for Google error: {e}")
            return False, None
    
    def check_for_error_message(self, driver, provider: str) -> Tuple[bool, Optional[str]]:
        """
        Check if the page contains an error message indicating the email doesn't exist.
        
        Args:
            driver: The WebDriver instance
            provider: The email provider
            
        Returns:
            Tuple[bool, Optional[str]]: (has_error, error_phrase)
        """
        # Check for Google-specific error message first using the specific XPath
        if provider == 'gmail.com' or provider == 'customGoogle':
            has_error, error_message = self.check_for_google_error(driver)
            if has_error:
                return True, error_message
            
            # Also check for the general error message
            try:
                error_div = driver.find_element(By.CSS_SELECTOR, 'div.dMNVAe[jsname="OZNMeb"][aria-live="assertive"]')
                if error_div and error_div.is_displayed():
                    error_text = error_div.text.strip()
                    if error_text and ("couldn't find" in error_text.lower() or 
                                     "try again with that email" in error_text.lower()):
                        return True, "Google account not found"
            except Exception:
                pass
        
        # Check for Yahoo-specific error message
        if provider == 'yahoo.com':
            has_error, error_message = self.check_for_yahoo_error(driver)
            if has_error:
                return True, error_message
        
        page_source = driver.page_source.lower()
        
        # Get provider-specific error phrases
        error_phrases = self.nonexistent_email_phrases.get(provider, []) + self.nonexistent_email_phrases['generic']
        
        # Check for each phrase
        for phrase in error_phrases:
            if phrase.lower() in page_source:
                return True, phrase
        
        # Check for specific error elements
        try:
            # Google error message
            google_error = driver.find_elements(By.XPATH, "//div[contains(@class, 'Ekjuhf') or contains(@class, 'o6cuMc')]")
            if google_error and any("couldn't find" in element.text.lower() for element in google_error if element.is_displayed()):
                return True, "Google account not found"
            
            # Microsoft error message
            microsoft_error = driver.find_elements(By.ID, "usernameError")
            if microsoft_error and any(element.is_displayed() for element in microsoft_error):
                return True, "Microsoft account not found"
        except Exception:
            pass
        
        return False, None
    
    def check_for_yahoo_error(self, driver) -> Tuple[bool, Optional[str]]:
        """
        Check for Yahoo-specific error message.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Tuple[bool, Optional[str]]: (has_error, error_message)
        """
        try:
            # Find the username-error element
            error_div = driver.find_element(By.CSS_SELECTOR, self.yahoo_error_selector)
            
            # Check if the error element is visible and not hidden
            if error_div and error_div.is_displayed():
                # Check if the class doesn't contain "hide"
                class_attr = error_div.get_attribute("class")
                if class_attr and "hide" not in class_attr:
                    error_text = error_div.text.strip()
                    if error_text:
                        return True, error_text
                    # Even if there's no text, if the error element is visible and not hidden, it's likely an error
                    return True, "Yahoo error element visible"
            
            return False, None
        except NoSuchElementException:
            return False, None
        except Exception as e:
            logger.error(f"Error checking for Yahoo error: {e}")
            return False, None
    
    def check_for_microsoft_multi_account(self, driver) -> Tuple[bool, Optional[str]]:
        """
        Check if the page contains a message indicating the email is used with multiple Microsoft accounts.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Tuple[bool, Optional[str]]: (has_multi_account, multi_account_text)
        """
        try:
            # Check for the specific div using the XPath
            try:
                multi_account_div = driver.find_element(By.XPATH, self.microsoft_multi_account_xpath)
                if multi_account_div and multi_account_div.is_displayed():
                    text = multi_account_div.text.strip()
                    for phrase in self.microsoft_multi_account_phrases:
                        if phrase.lower() in text.lower():
                            return True, text
                    # If the element exists but doesn't contain our phrases, it's likely still a multi-account scenario
                    if text:
                        return True, text
            except NoSuchElementException:
                pass
            
            # Also check by ID as a fallback
            multi_account_div = driver.find_elements(By.ID, "loginDescription")
            
            if multi_account_div:
                for div in multi_account_div:
                    if div.is_displayed():
                        text = div.text.strip()
                        for phrase in self.microsoft_multi_account_phrases:
                            if phrase.lower() in text.lower():
                                return True, text
                        # If the element exists but doesn't contain our phrases, it's likely still a multi-account scenario
                        if text:
                            return True, text
            
            # Check in the page source as well
            page_source = driver.page_source.lower()
            for phrase in self.microsoft_multi_account_phrases:
                if phrase.lower() in page_source:
                    return True, phrase
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for Microsoft multi-account: {e}")
            return False, None
    
    def get_page_heading(self, driver) -> Optional[str]:
        """
        Get the main heading of the page.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Optional[str]: The page heading if found, None otherwise
        """
        try:
            # Try common heading elements
            for selector in [
                "h1#headingText", # Google
                "div#loginHeader", # Microsoft
                "h1", 
                ".heading", 
                "[role='heading']"
            ]:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.is_displayed() and element.text.strip():
                        return element.text.strip()
            
            return None
        except Exception:
            return None
    
    def check_for_password_field(self, driver, provider: str, before_heading: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if the page contains a visible password field, indicating the email exists.
        
        Args:
            driver: The WebDriver instance
            provider: The email provider
            before_heading: The page heading before submitting the email
            
        Returns:
            Tuple[bool, Optional[str]]: (has_password, password_reason)
        """
        # Check for URL changes that indicate a valid email (Google specific)
        if provider in ['gmail.com', 'customGoogle']:
            current_url = driver.current_url
            # Check if URL changed to the password challenge URL
            if '/signin/challenge/pwd' in current_url:
                return True, "URL changed to password challenge"
        
        # Check for heading changes that indicate a valid email
        if provider in self.valid_email_indicators and before_heading:
            after_heading = self.get_page_heading(driver)
            if after_heading:
                # Check if heading changed from sign-in to password/welcome
                if (before_heading.lower() in [h.lower() for h in self.valid_email_indicators[provider]['heading_changes']['before']] and
                    after_heading.lower() in [h.lower() for h in self.valid_email_indicators[provider]['heading_changes']['after']]):
                    return True, "Heading changed to password prompt"
        
        # Check for visible password fields
        try:
            # Find all password fields
            password_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            
            # Check if any password field is visible and not hidden
            for field in password_fields:
                try:
                    # Check if the field is displayed
                    if not field.is_displayed():
                        continue
                    
                    # Check for attributes that indicate a hidden field
                    aria_hidden = field.get_attribute("aria-hidden")
                    tabindex = field.get_attribute("tabindex")
                    class_name = field.get_attribute("class")
                    
                    # Skip fields that are explicitly hidden
                    if (aria_hidden == "true" or 
                        tabindex == "-1" or 
                        any(hidden_class in (class_name or "") for hidden_class in ["moveOffScreen", "Hvu6D", "hidden"])):
                        continue
                    
                    # This is a visible password field
                    return True, "Visible password field found"
                except StaleElementReferenceException:
                    continue
            
            # Check for password-related labels or text that indicate a password prompt
            password_labels = driver.find_elements(By.XPATH, "//label[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'password')]")
            if password_labels and any(label.is_displayed() for label in password_labels):
                return True, "Password label found"
            
            # For Microsoft specifically, check for the password form
            if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                password_form = driver.find_elements(By.CSS_SELECTOR, "form[name='f1'][data-testid='passwordForm']")
                if password_form:
                    return True, "Password form found"
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for password field: {e}")
            return False, None
    
    def check_for_captcha(self, driver) -> Tuple[bool, Optional[str]]:
        """
        Check if the page contains a CAPTCHA challenge.
        
        Args:
            driver: The WebDriver instance
            
        Returns:
            Tuple[bool, Optional[str]]: (has_captcha, captcha_reason)
        """
        try:
            # Check for CAPTCHA image
            captcha_img = driver.find_elements(By.ID, "captchaimg")
            if captcha_img and any(img.is_displayed() for img in captcha_img):
                return True, "CAPTCHA image found"
            
            # Check for reCAPTCHA
            recaptcha = driver.find_elements(By.CSS_SELECTOR, ".g-recaptcha, iframe[src*='recaptcha']")
            if recaptcha and any(elem.is_displayed() for elem in recaptcha):
                return True, "reCAPTCHA found"
            
            # Check for CAPTCHA in URL
            if '/challenge/ipp' in driver.current_url or 'captcha' in driver.current_url.lower():
                return True, "CAPTCHA challenge in URL"
            
            # Check for CAPTCHA text input
            captcha_input = driver.find_elements(By.CSS_SELECTOR, "input[name='ca'], input[id='ca']")
            if captcha_input and any(input_field.is_displayed() for input_field in captcha_input):
                return True, "CAPTCHA input field found"
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking for CAPTCHA: {e}")
            return False, None
    
    def analyze_google_url(self, url: str, page_source: Optional[str] = None) -> Tuple[str, str]:
        """
        Analyze Google URL to determine the state of the login process.
        
        Args:
            url: The current URL
            page_source: The page source HTML
            
        Returns:
            Tuple[str, str]: (state, details)
        """
        # Check for different URL patterns
        if self.google_url_patterns['pwd_challenge'] in url:
            return "valid", "URL indicates password challenge (valid email)"
        elif self.google_url_patterns['rejected'] in url:
            # Rejected URL doesn't necessarily mean invalid email
            # It could be a security measure or rate limiting
            return "rejected", "URL indicates rejected login attempt (security measure)"
        elif self.google_url_patterns['captcha'] in url or 'captcha' in url.lower():
            return "captcha", "URL indicates CAPTCHA challenge"
        elif self.google_url_patterns['security_challenge'] in url:
            return "security", "URL indicates security challenge"
        elif self.google_url_patterns['TwoAcount'] in url:
            return "valid", "URL indicates multiple accounts (valid email)"
        elif 'shadowdisambiguate' in url:
            # Added check for shadowdisambiguate in URL which indicates valid email with multiple accounts
            return "valid", "URL indicates multiple accounts (shadowdisambiguate)"
        elif self.google_url_patterns['identifier'] in url:
            # Check if we're still on the identifier page but with an error message
            if page_source and any(phrase.lower() in page_source.lower() for phrase in self.nonexistent_email_phrases['gmail.com']):
                return "invalid", "Error message indicates invalid email"
            return "initial", "Still on identifier page"
        else:
            return "unknown", f"Unknown URL pattern: {url}"
    
    def verify_login(self, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email by attempting to log in and analyzing the response.
        
        Args:
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        # Extract domain for rate limiting
        _, domain = email.split('@')
        
        # Check rate limiting if rate limiter is set
        if self.rate_limiter and self.rate_limiter.is_rate_limited(domain):
            wait_time = self.rate_limiter.get_backoff_time(domain)
            logger.info(f"Login verification rate limited for {domain}, waiting {wait_time}s")
            time.sleep(wait_time)
            
            # Record this request
            if self.rate_limiter:
                self.rate_limiter.add_request(domain)
        
        # Start with Microsoft Edge as the default browser
        result = self._verify_with_edge(email, provider, login_url)
        
        # If the result is risky, try with undetected_chromedriver 
        # For both Google and Microsoft providers
        microsoft_providers = ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']
        google_providers = ['gmail.com', 'customGoogle']
        
        if result.category == RISKY and (provider in google_providers or provider in microsoft_providers):
            logger.info(f"Edge verification resulted in RISKY status for {email}. Trying with undetected_chromedriver...")
            result = self._verify_with_undetected_chrome(email, provider, login_url)
            
            # If still risky, try refreshing the page
            if result.category == RISKY:
                logger.info(f"Undetected Chrome verification resulted in RISKY status for {email}. Trying with page refresh...")
                result = self._verify_with_undetected_chrome_refresh(email, provider, login_url)
                
                # If still risky, try with a new browser instance
                if result.category == RISKY:
                    logger.info(f"Undetected Chrome with refresh resulted in RISKY status for {email}. Trying with new browser instance...")
                    result = self._verify_with_new_undetected_chrome(email, provider, login_url)
        
        return result
    
    def _verify_with_edge(self, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email using Microsoft Edge browser.
        
        Args:
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        logger.info(f"Starting Edge verification for {email}")
        return self._verify_with_browser("edge", email, provider, login_url)
    
    def _verify_with_undetected_chrome(self, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email using undetected_chromedriver.
        
        Args:
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        logger.info(f"Starting undetected Chrome verification for {email}")
        return self._verify_with_browser("chrome", email, provider, login_url)
    
    def _verify_with_undetected_chrome_refresh(self, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email using undetected_chromedriver with page refresh.
        
        Args:
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        logger.info(f"Starting undetected Chrome verification with page refresh for {email}")
        
        with self._browser_context("chrome") as driver:
            try:
                # Navigate to login page
                logger.info(f"Navigating to login page: {login_url}")
                driver.get(login_url)
                
                # Wait for page to load
                time.sleep(random.uniform(2, 4))
                
                # Refresh the page
                logger.info("Refreshing the page")
                driver.refresh()
                
                # Wait for page to reload
                time.sleep(random.uniform(2, 4))
                
                # Continue with normal verification process
                return self._perform_verification(driver, email, provider, login_url, "chrome_refresh")
                
            except Exception as e:
                logger.error(f"Error in undetected Chrome with refresh verification for {email}: {e}")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason=f"Error in Chrome with refresh verification: {str(e)}",
                    provider=provider,
                    details={"browser": "chrome_refresh"}
                )
    
    def _verify_with_new_undetected_chrome(self, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email using a new undetected_chromedriver instance.
        
        Args:
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        logger.info(f"Starting new undetected Chrome instance verification for {email}")
        
        # Close any existing driver and create a new one
        try:
            # Create a new undetected Chrome driver
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            
            # Add proxy if enabled
            if self.settings_model.is_enabled("proxy_enabled"):
                proxies = self.settings_model.get_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    options.add_argument(f'--proxy-server={proxy}')
            
            driver = uc.Chrome(options=options)
            
            try:
                # Navigate to login page
                logger.info(f"Navigating to login page with new Chrome instance: {login_url}")
                driver.get(login_url)
                
                # Wait for page to load
                time.sleep(random.uniform(2, 4))
                
                # Continue with normal verification process
                result = self._perform_verification(driver, email, provider, login_url, "new_chrome")
                
                return result
                
            except Exception as e:
                logger.error(f"Error in new Chrome instance verification for {email}: {e}")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason=f"Error in new Chrome instance verification: {str(e)}",
                    provider=provider,
                    details={"browser": "new_chrome"}
                )
            finally:
                # Make sure to close the driver
                if driver:
                    try:
                        driver.quit()
                    except Exception as e:
                        logger.error(f"Error closing new Chrome driver: {e}")
        
        except Exception as e:
            logger.error(f"Error creating new Chrome driver for {email}: {e}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Error creating new Chrome driver: {str(e)}",
                provider=provider,
                details={"browser": "new_chrome"}
            )
    
    def _verify_with_browser(self, browser_type: str, email: str, provider: str, login_url: str) -> EmailVerificationResult:
        """
        Verify email using the specified browser type.
        
        Args:
            browser_type: The type of browser to use
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            
        Returns:
            EmailVerificationResult: The verification result
        """
        with self._browser_context(browser_type) as driver:
            try:
                # Navigate to login page
                logger.info(f"Navigating to login page: {login_url} using {browser_type}")
                driver.get(login_url)
                
                # Wait for page to load
                time.sleep(random.uniform(2, 4))
                
                # Continue with normal verification process
                return self._perform_verification(driver, email, provider, login_url, browser_type)
                
            except Exception as e:
                logger.error(f"Error in {browser_type} verification for {email}: {e}")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason=f"Error in {browser_type} verification: {str(e)}",
                    provider=provider,
                    details={"browser": browser_type}
                )
    
    def _perform_verification(self, driver, email: str, provider: str, login_url: str, browser_type: str) -> EmailVerificationResult:
        """
        Perform the actual verification process with the given driver.
        
        Args:
            driver: The WebDriver instance
            email: The email address to verify
            provider: The email provider
            login_url: The login URL
            browser_type: The type of browser being used
            
        Returns:
            EmailVerificationResult: The verification result
        """
        try:
            # Store the initial URL for comparison later
            initial_url = driver.current_url
            logger.info(f"Initial URL: {initial_url}")
            
            # Get the initial page heading
            before_heading = self.get_page_heading(driver)
            logger.info(f"Initial page heading: {before_heading}")
            
            # Take screenshot before entering email
            self.take_screenshot(driver, email, f"before_email_{browser_type}")
            
            # Find email input field
            email_field = self.find_email_field(driver)
            
            if not email_field:
                logger.warning(f"Could not find email input field for {email}")
                # If we can't find the email field, it might be a custom login page
                logger.info("Login verification: Custom - Could not find email input field on login page")
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Could not find email input field on login page",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Enter email with human-like typing
            logger.info(f"Entering email: {email}")
            self.human_like_typing(email_field, email)
            
            # Random delay after typing (0.5-1.5 seconds)
            time.sleep(random.uniform(0.5, 1.5))
            
            # Find next button
            next_button = self.find_next_button(driver)
            
            if not next_button:
                logger.warning(f"Could not find next button for {email}")
                # If we can't find the next button, it might be a custom login page
                logger.info("Login verification: Custom - Could not find next/submit button on login page")
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Could not find next/submit button on login page",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Store the HTML of the Google error element before clicking next
            google_error_html_before = None
            if provider in ['gmail.com', 'customGoogle']:
                try:
                    error_div = driver.find_element(By.XPATH, self.google_error_xpath)
                    google_error_html_before = error_div.get_attribute('innerHTML')
                    logger.info(f"Google error element HTML before click: {google_error_html_before}")
                except NoSuchElementException:
                    pass
            
            # Store the Yahoo error element state before clicking next
            yahoo_error_state_before = None
            if provider == 'yahoo.com':
                try:
                    error_div = driver.find_element(By.CSS_SELECTOR, self.yahoo_error_selector)
                    yahoo_error_state_before = error_div.get_attribute('class')
                    logger.info(f"Yahoo error element class before click: {yahoo_error_state_before}")
                except NoSuchElementException:
                    pass
            
            # Check if the email input field contains the correct email before clicking next
            if self.settings_model.is_enabled("input_validation_enabled"):
                if not self.check_email_input_validity(driver, email_field, email):
                    logger.warning(f"Email input validation failed for {email}")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason="Email input validation failed",
                        provider=provider,
                        details={"current_url": driver.current_url, "browser": browser_type}
                    )
            
            # Take screenshot before clicking next
            self.take_screenshot(driver, email, f"before_next_{browser_type}")
            
            # Try to click next button with human-like movement
            logger.info("Clicking next button")
            click_success = self.human_like_move_and_click(driver, next_button)
            
            if not click_success:
                logger.error("All click methods failed")
                logger.info("Login verification: Risky - Could not click next button after multiple attempts")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason="Could not click next button after multiple attempts",
                    provider=provider,
                    details={"current_url": driver.current_url, "browser": browser_type}
                )
            
            # Wait for response with configurable delay
            wait_time = self.settings_model.get_browser_wait_time()
            time.sleep(wait_time)
            
            # Take screenshot after clicking next
            self.take_screenshot(driver, email, f"after_next_{browser_type}")
            
            # Get the current URL after clicking next
            current_url = driver.current_url
            logger.info(f"URL after clicking next: {current_url}")
            
            # For Yahoo provider, check URL changes first
            if provider == 'yahoo.com':
                # Check if URL changed to the challenge URL (valid email)
                if 'account/challenge/recaptcha' in current_url:
                    logger.info("Yahoo verification: Valid email - redirected to challenge page")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason="Email address exists (redirected to challenge page)",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
                
                # Check for Yahoo-specific error
                has_error, error_phrase = self.check_for_yahoo_error(driver)
                if has_error:
                    logger.info(f"Yahoo verification: Invalid - Email address does not exist ({error_phrase})")
                    return EmailVerificationResult(
                        email=email,
                        category=INVALID,
                        reason=f"Email address does not exist ({error_phrase})",
                        provider=provider,
                        details={"error_phrase": error_phrase, "current_url": current_url, "browser": browser_type}
                    )
            
            # Check for CAPTCHA after checking Yahoo URL changes
            has_captcha, captcha_reason = self.check_for_captcha(driver)
            if has_captcha:
                logger.warning(f"CAPTCHA detected for {email}: {captcha_reason}")
                logger.info(f"Login verification: Risky - CAPTCHA challenge encountered: {captcha_reason}")
                return EmailVerificationResult(
                    email=email,
                    category=RISKY,
                    reason=f"CAPTCHA challenge encountered: {captcha_reason}",
                    provider=provider,
                    details={"current_url": current_url, "browser": browser_type}
                )
            
            # Get page source for error checking
            page_source = driver.page_source
            
            # For Google providers, check if the error element HTML changed after clicking next
            if provider in ['gmail.com', 'customGoogle']:
                try:
                    error_div = driver.find_element(By.XPATH, self.google_error_xpath)
                    google_error_html_after = error_div.get_attribute('innerHTML')
                    
                    # If the HTML changed and now contains error indicators
                    if (google_error_html_before != google_error_html_after and 
                        ("Ekjuhf Jj6Lae" in google_error_html_after or 
                         "<svg aria-hidden=\"true\" class=\"Qk3oof xTjuxe\"" in google_error_html_after)):
                        
                        logger.info(f"Google verification: Invalid - Error element HTML changed indicating invalid email")
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason="Email address does not exist (error element HTML changed)",
                            provider=provider,
                            details={"error_html": google_error_html_after, "browser": browser_type}
                        )
                except NoSuchElementException:
                    pass
            
            # Check for error message first (for all providers)
            has_error, error_phrase = self.check_for_error_message(driver, provider)
            if has_error:
                logger.info(f"Login verification: Invalid - Email address does not exist ({error_phrase})")
                return EmailVerificationResult(
                    email=email,
                    category=INVALID,
                    reason=f"Email address does not exist ({error_phrase})",
                    provider=provider,
                    details={"error_phrase": error_phrase, "current_url": current_url, "browser": browser_type}
                )
            
            # For Microsoft providers, check for multi-account message
            if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                has_multi_account, multi_account_text = self.check_for_microsoft_multi_account(driver)
                if has_multi_account or "signin/shadowdisambiguate" in driver.current_url:
                    logger.info("Microsoft verification: Valid email - multiple accounts detected")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason="Email exists (multiple Microsoft accounts)",
                        provider=provider,
                        details={"multi_account_text": multi_account_text, "browser": browser_type}
                    )
            
            # For Google providers (both gmail.com and customGoogle)
            if provider in ['gmail.com', 'customGoogle']:
                # Analyze Google URL to determine state
                state, details = self.analyze_google_url(current_url, page_source)
                logger.info(f"Google URL analysis: {state} - {details}")
                
                if state == "valid":
                    logger.info(f"Google verification: Valid - Email address exists ({details})")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email address exists ({details})",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
                elif state == "invalid":
                    logger.info(f"Google verification: Invalid - Email address does not exist ({details})")
                    return EmailVerificationResult(
                        email=email,
                        category=INVALID,
                        reason=f"Email address does not exist ({details})",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
                elif state == "rejected":
                    # For rejected URLs, we need to check if there's an error message
                    # indicating the email doesn't exist
                    has_error, error_phrase = self.check_for_error_message(driver, provider)
                    if has_error:
                        logger.info(f"Google verification: Invalid - Email address does not exist ({error_phrase})")
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason=f"Email address does not exist ({error_phrase})",
                            provider=provider,
                            details={"error_phrase": error_phrase, "current_url": current_url, "browser": browser_type}
                        )
                    
                    # If no clear error message, check for password field
                    has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                    if has_password:
                        logger.info(f"Google verification: Valid - Email address exists ({password_reason})")
                        return EmailVerificationResult(
                            email=email,
                            category=VALID,
                            reason=f"Email address exists ({password_reason})",
                            provider=provider,
                            details={"current_url": current_url, "browser": browser_type}
                        )
                    
                    # If we can't determine, mark as risky
                    logger.info("Google verification: Risky - Rejected login but could not determine if email exists")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason=f"Rejected login but could not determine if email exists",
                        provider=provider,
                        details={"current_url": current_url, "browser": browser_type}
                    )
                elif state == "captcha":
                    logger.info(f"Google verification: Risky - CAPTCHA challenge encountered ({details})")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason=f"CAPTCHA challenge encountered ({details})",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
                elif state == "security":
                    # If we hit a security challenge, the email likely exists
                    logger.info("Google verification: Valid - Email likely exists (security challenge)")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email likely exists (security challenge)",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
                elif state == "initial":
                    # Still on the identifier page, check for error messages
                    has_error, error_phrase = self.check_for_error_message(driver, provider)
                    if has_error:
                        logger.info(f"Google verification: Invalid - Email address does not exist ({error_phrase})")
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason=f"Email address does not exist ({error_phrase})",
                            provider=provider,
                            details={"error_phrase": error_phrase, "browser": browser_type}
                        )
                    else:
                        # No error message but still on identifier page - might be a UI issue
                        logger.info("Google verification: Risky - Could not proceed past identifier page (no error message)")
                        return EmailVerificationResult(
                            email=email,
                            category=RISKY,
                            reason="Could not proceed past identifier page (no error message)",
                            provider=provider,
                            details={"current_url": current_url, "browser": browser_type}
                        )
                else:  # Unknown state
                    # Check if we can find a password field anyway
                    has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                    if has_password:
                        logger.info(f"Google verification: Valid - Email address exists ({password_reason})")
                        return EmailVerificationResult(
                            email=email,
                            category=VALID,
                            reason=f"Email address exists ({password_reason})",
                            provider=provider,
                            details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                        )
                    
                    # Check for error messages
                    has_error, error_phrase = self.check_for_error_message(driver, provider)
                    if has_error:
                        logger.info(f"Google verification: Invalid - Email address does not exist ({error_phrase})")
                        return EmailVerificationResult(
                            email=email,
                            category=INVALID,
                            reason=f"Email address does not exist ({error_phrase})",
                            provider=provider,
                            details={"error_phrase": error_phrase, "browser": browser_type}
                        )
                    
                    # If we can't determine, mark as risky
                    logger.info(f"Google verification: Risky - Unknown Google login state: {details}")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason=f"Unknown Google login state: {details}",
                        provider=provider,
                        details={"initial_url": initial_url, "current_url": current_url, "browser": browser_type}
                    )
            
            # For non-Google providers, continue with the original logic
            # Check for password field or heading changes
            has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
            if has_password:
                logger.info(f"Login verification: Valid email - {password_reason}")
                return EmailVerificationResult(
                    email=email,
                    category=VALID,
                    reason=f"Email address exists ({password_reason})",
                    provider=provider,
                    details={"browser": browser_type}
                )
            
            # Check if we were redirected to a custom domain login
            original_domain = login_url.split('/')[2]
            current_domain = driver.current_url.split('/')[2]
            
            # If we're redirected to a different domain, it might be a custom login
            if original_domain != current_domain and "login" in driver.current_url.lower():
                # Try to find password field on the new page
                has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                if has_password:
                    logger.info(f"Login verification: Valid email - {password_reason} after redirect")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email address exists ({password_reason} after redirect)",
                        provider=provider,
                        details={"redirect_url": driver.current_url, "browser": browser_type}
                    )
                
                # If we can't determine, mark as custom
                logger.info("Login verification: Custom - redirected to custom login page")
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Redirected to custom login page",
                    provider=provider,
                    details={"redirect_url": driver.current_url, "browser": browser_type}
                )
            
            # If we can't find a password field or error message, check if we're still on the same page
            if login_url.split('?')[0] in driver.current_url.split('?')[0]:
                # We're still on the login page, but no clear error message
                # For Microsoft, mark as risky if no error message (changed from valid as per requirements)
                if provider in ['outlook.com', 'hotmail.com', 'live.com', 'microsoft.com', 'office365.com']:
                    logger.info("Microsoft verification: Risky - no rejection or error")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,  # Changed from VALID to RISKY as requested
                        reason="Could not determine if email exists (no rejection or error)",
                        provider=provider,
                        details={"current_url": driver.current_url, "browser": browser_type}
                    )
                else:
                    # For other providers, mark as risky
                    logger.info("Login verification: Risky - could not determine if email exists")
                    return EmailVerificationResult(
                        email=email,
                        category=RISKY,
                        reason="Could not determine if email exists (no password prompt or error)",
                        provider=provider,
                        details={"current_url": driver.current_url, "browser": browser_type}
                    )
            else:
                # We were redirected somewhere else
                # Try one more time to check for password field
                has_password, password_reason = self.check_for_password_field(driver, provider, before_heading)
                if has_password:
                    logger.info(f"Login verification: Valid email - {password_reason} after redirect")
                    return EmailVerificationResult(
                        email=email,
                        category=VALID,
                        reason=f"Email address exists ({password_reason} after redirect)",
                        provider=provider,
                        details={"redirect_url": driver.current_url, "browser": browser_type}
                    )
                
                # If still no password field, mark as custom
                logger.info("Login verification: Custom - redirected to another page")
                return EmailVerificationResult(
                    email=email,
                    category=CUSTOM,
                    reason="Redirected to another page",
                    provider=provider,
                    details={"redirect_url": driver.current_url, "browser": browser_type}
                )
        
        except Exception as e:
            logger.error(f"Error in verification process: {e}")
            return EmailVerificationResult(
                email=email,
                category=RISKY,
                reason=f"Verification error: {str(e)}",
                provider=provider,
                details={"browser": browser_type}
            )