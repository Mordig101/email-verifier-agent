import os
import sys
import time
import random
import logging
import threading
import queue
import multiprocessing
from multiprocessing import Queue
import subprocess
from typing import Dict, List, Any, Optional, Callable
from models.common import EmailVerificationResult, VALID, INVALID, RISKY, CUSTOM

logger = logging.getLogger(__name__)

class MultiTerminalModel:
    """Model for multi-terminal support."""
    
    def __init__(self, settings_model):
        """
        Initialize the multi-terminal model.
        
        Args:
            settings_model: The settings model instance
        """
        self.settings_model = settings_model
        
        # Multi-terminal support
        self.multi_terminal_enabled = self.settings_model.is_enabled("multi_terminal_enabled")
        self.terminal_count = self.settings_model.get_terminal_count()
        self.email_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.terminal_threads = []
        self.terminal_processes = []
        
        # Define max terminals with a reasonable upper limit
        self.max_terminals = 32  # Increased from 8 to 32
        
        # Lock for thread safety
        self.lock = threading.RLock()
    
    def get_lock(self):
        """
        Get the lock for thread safety.
        
        Returns:
            threading.RLock: The lock
        """
        return self.lock
    
    def enable_multi_terminal(self) -> None:
        """Enable multi-terminal support."""
        self.multi_terminal_enabled = True
        self.settings_model.set("multi_terminal_enabled", "True", True)
    
    def disable_multi_terminal(self) -> None:
        """Disable multi-terminal support."""
        self.multi_terminal_enabled = False
        self.settings_model.set("multi_terminal_enabled", "False", False)
    
    def set_terminal_count(self, count: int) -> None:
        """
        Set the number of terminals to use.
        
        Args:
            count: The number of terminals
        """
        # Validate count with warning instead of silent capping
        max_count = self.max_terminals
        if count > max_count:
            logger.warning(f"Requested {count} terminals exceeds recommended maximum of {max_count}.")
            logger.warning("Using too many terminals may impact system performance.")
            # Allow it anyway if the user insists
        
        # Set a reasonable minimum
        self.terminal_count = max(1, count)
        self.settings_model.set("terminal_count", str(self.terminal_count), True)
        logger.info(f"Terminal count set to {self.terminal_count}")
    
    def _process_worker(self, terminal_id: int, emails: List[str], result_queue: multiprocessing.Queue) -> None:
        """
        Worker function for multi-terminal support using multiprocessing.
        
        Args:
            terminal_id: The terminal ID
            emails: List of emails to verify
            result_queue: Queue to put results in
        """
        logger.info(f"Terminal {terminal_id} process started")
        
        for email in emails:
            try:
                # Create a temporary file to store the email
                emails_file = f"terminal_{terminal_id}_emails.txt"
                with open(emails_file, 'w', encoding='utf-8') as f:
                    f.write(email)
                
                # Start a new process for this email
                cmd = [sys.executable, "main.py", "--terminal", str(terminal_id), "--emails", emails_file]
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                # Wait for the process to complete
                stdout, stderr = process.communicate()
                
                # Parse the result
                for line in stdout.splitlines():
                    if line.startswith("RESULT:"):
                        _, email, category = line.split(":")
                        
                        # Put the result in the result queue
                        result_queue.put((email, {
                            "email": email,
                            "category": category,
                            "reason": f"Verified by terminal {terminal_id}",
                            "provider": "unknown",
                            "details": {"terminal_id": terminal_id}
                        }))
                
                # Clean up
                if os.path.exists(emails_file):
                    os.remove(emails_file)
                
                # Add a delay to avoid rate limiting
                time.sleep(random.uniform(1, 2))
            
            except Exception as e:
                logger.error(f"Terminal {terminal_id} error: {e}")
                # Put an error result in the queue
                result_queue.put((email, {
                    "email": email,
                    "category": RISKY,
                    "reason": f"Verification error: {str(e)}",
                    "provider": "unknown",
                    "details": {"error": str(e), "terminal_id": terminal_id}
                }))
                
                # Add a delay before continuing
                time.sleep(random.uniform(5, 10))
        
        logger.info(f"Terminal {terminal_id} process finished")
    
    def _start_terminal_process(self, terminal_id: int, emails: List[str]) -> tuple:
        """
        Start a new terminal process for multi-terminal support.
        
        Args:
            terminal_id: The terminal ID
            emails: List of emails to verify
            
        Returns:
            tuple: The process and result queue
        """
        # Create a shared queue for results
        result_queue = Queue()
        
        # Start process with the queue
        process = multiprocessing.Process(
            target=self._process_worker,
            args=(terminal_id, emails, result_queue)
        )
        
        # Initialize process before starting
        process.daemon = True
        
        # Start the process
        try:
            process.start()
            logger.info(f"Started terminal {terminal_id} process with PID {process.pid}")
        except Exception as e:
            logger.error(f"Error starting terminal {terminal_id} process: {e}")
            # Return a dummy process and queue in case of error
            return None, result_queue
        
        return process, result_queue
    
    def _terminal_worker(self, terminal_id: int, verify_email_func: Callable) -> None:
        """
        Worker function for multi-terminal support using threading.
        
        Args:
            terminal_id: The terminal ID
            verify_email_func: Function to verify an email
        """
        logger.info(f"Terminal {terminal_id} started")
        
        while True:
            try:
                # Get an email from the queue
                email = self.email_queue.get(block=False)
                
                # Verify the email
                logger.info(f"Terminal {terminal_id} verifying {email}")
                result = verify_email_func(email)
                
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
    
    def batch_verify(self, emails: List[str], verify_email_func: Callable) -> Dict[str, EmailVerificationResult]:
        """
        Verify multiple email addresses.
        
        Args:
            emails: List of emails to verify
            verify_email_func: Function to verify an email
            
        Returns:
            Dict[str, EmailVerificationResult]: Dictionary of verification results
        """
        results = {}
        
        # Check if multi-terminal support is enabled
        if self.multi_terminal_enabled and len(emails) > 1:
            # Calculate optimal terminal count based on email count
            optimal_terminal_count = min(self.terminal_count, len(emails))
            
            # Log terminal usage
            logger.info(f"Using {optimal_terminal_count} terminals to verify {len(emails)} emails")
            
            # If using real multiple terminals with multiprocessing
            if self.settings_model.is_enabled("real_multiple_terminals"):
                # Split emails into chunks for each terminal
                chunk_size = max(1, len(emails) // optimal_terminal_count)
                email_chunks = []
                
                for i in range(optimal_terminal_count):
                    start_idx = i * chunk_size
                    end_idx = start_idx + chunk_size if i < optimal_terminal_count - 1 else len(emails)
                    email_chunks.append(emails[start_idx:end_idx])
                
                # Start terminal processes
                processes = []
                result_queues = []
                
                for i, chunk in enumerate(email_chunks):
                    try:
                        process, result_queue = self._start_terminal_process(i+1, chunk)
                        if process:
                            processes.append(process)
                            result_queues.append(result_queue)
                        else:
                            # If process creation failed, verify emails in this chunk directly
                            for email in chunk:
                                results[email] = verify_email_func(email)
                                time.sleep(random.uniform(2, 4))
                    except Exception as e:
                        logger.error(f"Error starting terminal process {i+1}: {e}")
                        # Verify emails in this chunk directly
                        for email in chunk:
                            results[email] = verify_email_func(email)
                            time.sleep(random.uniform(2, 4))
                
                # Wait for all processes to complete
                for process in processes:
                    try:
                        process.join(timeout=300)  # 5 minute timeout
                        if process.is_alive():
                            logger.warning(f"Process {process.pid} timed out, terminating")
                            process.terminate()
                    except Exception as e:
                        logger.error(f"Error joining process: {e}")
                
                # Get results from all queues
                for result_queue in result_queues:
                    try:
                        while not result_queue.empty():
                            email, result_dict = result_queue.get(timeout=1)
                            results[email] = EmailVerificationResult(
                                email=result_dict["email"],
                                category=result_dict["category"],
                                reason=result_dict["reason"],
                                provider=result_dict["provider"],
                                details=result_dict.get("details")
                            )
                    except Exception as e:
                        logger.error(f"Error getting results from queue: {e}")
            else:
                # Using thread-based multi-terminal
                # Put all emails in the queue
                for email in emails:
                    self.email_queue.put(email)
                
                # Start terminal threads
                for i in range(min(self.terminal_count, len(emails))):
                    thread = threading.Thread(target=self._terminal_worker, args=(i+1, verify_email_func))
                    thread.daemon = True
                    thread.start()
                    self.terminal_threads.append(thread)
                
                # Wait for all emails to be verified
                self.email_queue.join()
                
                # Get results from the result queue
                while not self.result_queue.empty():
                    email, result = self.result_queue.get()
                    results[email] = result
        else:
            # Single-terminal verification
            for email in emails:
                results[email] = verify_email_func(email)
                # Add a delay between checks to avoid rate limiting
                time.sleep(random.uniform(2, 4))
        
        return results