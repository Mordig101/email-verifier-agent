import os
import csv
import sys
import time
import subprocess
import threading
import argparse
from typing import List, Dict, Any

def create_directory(directory: str) -> None:
    """Create directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)

def divide_emails(csv_path: str, num_terminals: int) -> List[str]:
    """
    Divide emails from a CSV file into chunks for each terminal.
    
    Args:
        csv_path: Path to the CSV file containing emails
        num_terminals: Number of terminals to divide emails among
        
    Returns:
        List[str]: List of paths to the chunked CSV files
    """
    # Create terminal directory if it doesn't exist
    terminal_dir = "terminal"
    create_directory(terminal_dir)
    
    # Read emails from CSV file
    emails = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                email = line.strip()
                if '@' in email:  # Basic validation
                    emails.append(email)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []
    
    if not emails:
        print("No valid emails found in the CSV file.")
        return []
    
    # Remove header if it looks like one
    if not '@' in emails[0] or emails[0].lower() == "email":
        emails = emails[1:]
        if not emails:
            print("No valid emails found after removing header.")
            return []
    
    # Calculate emails per terminal - distribute evenly
    total_emails = len(emails)
    emails_per_terminal = total_emails // num_terminals
    remainder = total_emails % num_terminals
    
    # Divide emails into chunks
    chunk_files = []
    start_idx = 0
    
    for i in range(num_terminals):
        # Add one extra email to first 'remainder' terminals
        current_count = emails_per_terminal + (1 if i < remainder else 0)
        
        end_idx = start_idx + current_count
        chunk_emails = emails[start_idx:end_idx]
        chunk_file = os.path.join(terminal_dir, f"T{i+1}email.csv")
        
        # Write chunk to CSV file
        with open(chunk_file, 'w', encoding='utf-8', newline='') as f:
            for email in chunk_emails:
                f.write(f"{email}\n")
        
        chunk_files.append(chunk_file)
        print(f"Created {chunk_file} with {len(chunk_emails)} emails ({start_idx+1}-{end_idx} of {total_emails})")
        
        # Update start index for next chunk
        start_idx = end_idx
    
    return chunk_files

def run_terminal(terminal_id: int, csv_path: str, output_queue: List, run_in_background: bool = False) -> None:
    """
    Run main.py in a terminal with automated input and capture output.
    
    Args:
        terminal_id: ID of the terminal
        csv_path: Path to the CSV file containing emails for this terminal
        output_queue: Queue to store terminal output
        run_in_background: Whether to run terminals in background mode
    """
    try:
        # Get absolute path to CSV file
        abs_csv_path = os.path.abspath(csv_path)
        
        # Format current date for filename
        current_date = time.strftime("%Y%m%d")
        
        # Create all files in the terminal directory
        terminal_dir = "terminal"
        input_file = os.path.join(terminal_dir, f"terminal_input_{terminal_id}.txt")
        batch_file = os.path.join(terminal_dir, f"terminal_cmd_{terminal_id}.bat")
        log_file = os.path.join(terminal_dir, f"terminal_log_{terminal_id}.txt")
        hidden_runner = os.path.join(terminal_dir, f"hidden_runner_{terminal_id}.vbs")
        
        # Calculate optimal thread count per terminal based on system
        # Use 2 threads per terminal by default, but lower for high terminal counts
        import multiprocessing
        available_cores = multiprocessing.cpu_count()
        threads_per_terminal = max(1, min(2, available_cores // max(1, terminal_id // 4)))
        
        # Create input file with automated responses
        with open(input_file, 'w') as f:
            f.write('2\n')  # Option 2: Verify multiple emails
            f.write('1\n')  # Option 1: Load from CSV file
            f.write(f'{abs_csv_path}\n')  # CSV path
            f.write('y\n')  # Use multi-terminal: yes
            f.write(f'{threads_per_terminal}\n')  # Number of threads per terminal (adaptive)
            f.write('n\n')  # Use real multiple terminals: no
            f.write('n\n')  # Save verification statistics: no
            f.write(f'TermiVerif{terminal_id}_{current_date}\n')  # Name for statistics
        
        # Create a batch file to run the command with input redirection and output capture
        with open(batch_file, 'w') as f:
            f.write('@echo off\n')
            f.write(f'title Email Verifier Terminal {terminal_id}\n')
            f.write(f'cd /d "{os.getcwd()}"\n')
            f.write(f'echo Terminal {terminal_id} starting... > "{log_file}"\n')
            # Redirect input from file, and output to log file
            f.write(f'python main.py < "{input_file}" > "{log_file}" 2>&1\n')
            f.write(f'echo Terminal {terminal_id} completed. >> "{log_file}"\n')
            f.write(f'echo Completed > "{terminal_dir}\\T{terminal_id}_completed.txt"\n')
            if not run_in_background:
                f.write('timeout /t 5 /nobreak\n')  # Wait 5 seconds
            f.write('exit\n')  # Close window automatically
        
        # Create a VBScript to run the batch file with a hidden window (for background mode)
        if run_in_background:
            with open(hidden_runner, 'w') as f:
                f.write('Set WshShell = CreateObject("WScript.Shell")\n')
                f.write('Set oExec = WshShell.Exec("cmd /c ""' + batch_file + '"" ' + str(terminal_id) + '")\n')
                f.write('Do While oExec.Status = 0\n')
                f.write('    WScript.Sleep 100\n')
                f.write('Loop\n')
        
        # Start process
        if run_in_background:
            # Run VBScript which runs the batch file with a hidden window
            subprocess.Popen(
                ['wscript.exe', hidden_runner],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            output_queue.append((terminal_id, f"Started in background mode"))
        else:
            # Run normally in separate visible window
            subprocess.Popen(
                f'start "Terminal {terminal_id}" cmd /c "{batch_file}" {terminal_id}',
                shell=True
            )
        
        # Add initial message to output queue
        output_queue.append((terminal_id, f"Terminal {terminal_id} started with CSV: {os.path.basename(csv_path)}"))
        
        # Start the log file reader thread
        log_reader_thread = threading.Thread(
            target=read_log_file,
            args=(terminal_id, log_file, output_queue)
        )
        log_reader_thread.daemon = True
        log_reader_thread.start()
        
    except Exception as e:
        print(f"Error in terminal {terminal_id}: {e}")
        output_queue.append((terminal_id, f"Error: {str(e)}"))

def read_log_file(terminal_id: int, log_file: str, output_queue: List) -> None:
    """
    Read and process log file for a terminal.
    
    Args:
        terminal_id: ID of the terminal
        log_file: Path to the log file
        output_queue: Queue to store terminal output
    """
    last_position = 0
    
    # Wait for log file to be created (with timeout)
    wait_start = time.time()
    while not os.path.exists(log_file):
        time.sleep(0.5)
        if time.time() - wait_start > 60:  # 1 minute timeout
            output_queue.append((terminal_id, "Warning: Log file was not created after 60 seconds"))
            return
    
    # Check if verification is complete
    completion_marker = os.path.join(os.path.dirname(log_file), f"T{terminal_id}_completed.txt")
    
    # Continue until verification is complete
    while not os.path.exists(completion_marker):
        try:
            # Read new content from log file
            with open(log_file, 'r', encoding='utf-8') as f:
                f.seek(last_position)
                new_content = f.read()
                last_position = f.tell()
            
            # Process new content
            if new_content:
                lines = new_content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        # Skip browser errors and warnings
                        if any(error_text in line for error_text in ["ERROR:", "WARNING:", "E0000", "interface_endpoint", "blink.mojom"]):
                            continue
                            
                        # Filter and format interesting lines
                        if "Verifying" in line or any(s in line for s in ["VALID", "INVALID", "RISKY", "CUSTOM"]):
                            # Add to output queue
                            output_queue.append((terminal_id, line))
        except Exception as e:
            # Ignore errors, they might happen if the file is being written to
            pass
        
        # Sleep to avoid high CPU usage
        time.sleep(0.5)
    
    # Process any remaining content after completion
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            f.seek(last_position)
            new_content = f.read()
        
        if new_content:
            lines = new_content.split('\n')
            for line in lines:
                if line.strip():
                    if "Verifying" in line or "VALID" in line or "INVALID" in line or "RISKY" in line or "CUSTOM" in line:
                        output_queue.append((terminal_id, line.strip()))
    except Exception:
        pass
    
    # Add completion message
    output_queue.append((terminal_id, "Verification completed!"))

def display_progress(output_queue: List, terminal_dir: str, num_terminals: int) -> None:
    """
    Display progress from all terminals in real-time.
    
    Args:
        output_queue: Queue containing terminal output
        terminal_dir: Directory containing terminal files
        num_terminals: Number of terminals
    """
    # Dictionary to store terminal output by terminal ID
    terminal_outputs = {i+1: [] for i in range(num_terminals)}
    last_display_time = time.time()
    displayed_lines = set()
    
    # Calculate maximum number of verification lines to show per terminal
    max_verification_lines = 10
    
    # Continue until all terminals have completed
    while not check_completion(terminal_dir, num_terminals):
        current_time = time.time()
        
        # Display new output every second
        if current_time - last_display_time >= 1:
            # Get all new lines from the queue
            new_lines = []
            for terminal_id, line in output_queue:
                line_key = f"{terminal_id}:{line}"
                if line_key not in displayed_lines:
                    new_lines.append((terminal_id, line))
                    displayed_lines.add(line_key)
                    terminal_outputs[terminal_id].append(line)
            
            # Clear screen for better display
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # Display header
            print("Email Verification Terminal Controller")
            print("=====================================")
            print(f"Monitoring {num_terminals} terminal(s)...\n")
            
            # Display terminal outputs
            for terminal_id in range(1, num_terminals + 1):
                print(f"\nTerminal {terminal_id}:")
                
                # Get the latest verification lines for this terminal
                terminal_lines = terminal_outputs.get(terminal_id, [])
                
                # Extract verification lines (containing "Verifying" or verification results)
                verification_lines = [l for l in terminal_lines if "Verifying" in l or any(s in l for s in ["VALID", "INVALID", "RISKY", "CUSTOM"])]
                
                # Display the most recent verification lines
                if verification_lines:
                    for line in verification_lines[-max_verification_lines:]:
                        print(f"  {line}")
                else:
                    print("  Waiting for verification to start...")
                
                # Check if this terminal has completed
                if check_terminal_completion(terminal_dir, terminal_id):
                    print("  ✓ Verification completed!")
            
            # Show progress summary
            completed = sum(1 for i in range(1, num_terminals + 1) if check_terminal_completion(terminal_dir, i))
            print(f"\nProgress: {completed}/{num_terminals} terminals completed")
            
            last_display_time = current_time
        
        # Sleep to avoid high CPU usage
        time.sleep(0.1)
    
    # Final display after all terminals complete
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("Email Verification Terminal Controller")
    print("=====================================")
    print("All terminals have completed processing!\n")
    
    # Display summary for each terminal
    for terminal_id in range(1, num_terminals + 1):  # Changed from num_terminals + 8
        print(f"\nTerminal {terminal_id} Results:")
        
        # Filter for result lines (containing verification results)
        terminal_lines = terminal_outputs.get(terminal_id, [])
        result_lines = [l for l in terminal_lines if any(s in l for s in ["VALID", "INVALID", "RISKY", "CUSTOM"]) and "Verifying" not in l]
        
        if result_lines:
            for line in result_lines:
                print(f"  {line}")
        else:
            print("  No results found")

def check_completion(terminal_dir: str, num_terminals: int) -> bool:
    """
    Check if all terminals have completed.
    
    Args:
        terminal_dir: Directory containing terminal files
        num_terminals: Number of terminals
        
    Returns:
        bool: True if all terminals have completed, False otherwise
    """
    for terminal_id in range(1, num_terminals + 1):
        if not check_terminal_completion(terminal_dir, terminal_id):
            return False
    return True

def check_terminal_completion(terminal_dir: str, terminal_id: int) -> bool:
    """
    Check if a specific terminal has completed.
    
    Args:
        terminal_dir: Directory containing terminal files
        terminal_id: ID of the terminal to check
        
    Returns:
        bool: True if the terminal has completed, False otherwise
    """
    completion_marker = os.path.join(terminal_dir, f"T{terminal_id}_completed.txt")
    return os.path.exists(completion_marker)

def cleanup_files(terminal_dir: str, num_terminals: int) -> None:
    """
    Clean up all temporary files after completion with retries.
    
    Args:
        terminal_dir: Directory containing terminal files
        num_terminals: Number of terminals
    """
    print("Cleaning up temporary files...")
    
    # First wait longer to ensure all processes are done
    print("Waiting for terminal processes to fully exit...")
    time.sleep(10)
    
    # Files to delete
    file_patterns = [
        "terminal_cmd_*.bat",    # Delete batch files first
        "hidden_runner_*.vbs",   # VBS scripts
        "T*_completed.txt",      # Then completion markers
        "terminal_log_*.txt",    # Log files
        "terminal_input_*.txt",  # Input files last (most likely to still be in use)
        "T*email.csv"            # Chunk CSV files
    ]
    
    # Track files that failed to delete for retry
    failed_files = []
    
    import glob
    for pattern in file_patterns:
        files = glob.glob(os.path.join(terminal_dir, pattern))
        for file in files:
            try:
                os.remove(file)
                print(f"Deleted: {file}")
            except Exception as e:
                print(f"Failed to delete {file}: {e}")
                failed_files.append(file)
    
    # Retry deletion with increasing delays
    if failed_files:
        print(f"{len(failed_files)} files could not be deleted. Will retry...")
        
        for retry in range(3):  # Try 3 times
            if not failed_files:
                break
                
            # Increase wait time with each retry
            wait_time = 5 * (retry + 1)
            print(f"Waiting {wait_time} seconds before retry #{retry+1}...")
            time.sleep(wait_time)
            
            # Try to kill any cmd processes that might be holding the files
            try:
                subprocess.run("taskkill /f /im cmd.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("Forcefully closed any remaining cmd processes")
            except:
                pass
                
            # Try deleting again
            still_failed = []
            for file in failed_files:
                try:
                    os.remove(file)
                    print(f"Successfully deleted on retry: {file}")
                except Exception as e:
                    print(f"Still failed to delete {file}: {e}")
                    still_failed.append(file)
            
            failed_files = still_failed
    
    if failed_files:
        print(f"Warning: {len(failed_files)} files could not be deleted:")
        for file in failed_files:
            print(f"  - {file}")
        print("\nYou may need to manually delete these files when they are no longer in use.")
    else:
        print("Cleanup completed successfully.")
        
    # Consider scheduling a cleanup task to run later
    try:
        # Create a batch file to clean up remaining files
        cleanup_bat = os.path.join(terminal_dir, "delayed_cleanup.bat")
        with open(cleanup_bat, "w") as f:
            f.write("@echo off\n")
            f.write("rem Wait for 1 minute\n")
            f.write("timeout /t 60 /nobreak\n")
            f.write("rem Delete remaining files\n")
            for pattern in file_patterns:
                f.write(f'del /q "{os.path.join(terminal_dir, pattern)}"\n')
            f.write("rem Delete this batch file\n")
            f.write(f'del /q "{cleanup_bat}"\n')
        
        # Run the cleanup batch silently in the background
        subprocess.Popen(
            ["start", "/min", "cmd", "/c", cleanup_bat],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("Scheduled delayed cleanup after 1 minute...")
    except Exception as e:
        print(f"Failed to schedule delayed cleanup: {e}")

def count_emails_in_csv(csv_path: str) -> int:
    """
    Count valid emails in a CSV file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        int: Number of valid emails in the file
    """
    email_count = 0
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                email = line.strip()
                if '@' in email:  # Basic validation
                    email_count += 1
        
        # Check if first line might be a header
        if email_count > 0:
            with open(csv_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if not '@' in first_line or first_line.lower() == "email":
                    email_count -= 1
    except Exception as e:
        print(f"Error reading CSV file: {e}")
    
    return email_count

def main():
    """Main function to control multiple terminals."""
    print("Email Verification Terminal Controller")
    print("=====================================")
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Control multiple terminals for email verification")
    parser.add_argument("--num-terminals", type=int, help="Number of terminals to use")
    parser.add_argument("--csv-path", type=str, help="Path to CSV file containing emails")
    parser.add_argument("--background", action="store_true", help="Run terminals in background mode")
    args = parser.parse_args()
    
    # Get number of terminals
    num_terminals = args.num_terminals
    if not num_terminals:
        try:
            # Remove the upper limit of 8
            num_terminals = int(input("How many terminal windows do you want to use? (1 or more): "))
            
            # Show warning for high terminal counts but don't enforce a limit
            if num_terminals > 8:
                print(f"\nNote: You've selected {num_terminals} terminals. Using a large number of terminals may impact system performance.")
                confirm = input("Continue with this many terminals? (y/n): ").lower()
                if not confirm.startswith('y'):
                    new_count = int(input("Enter a new terminal count: "))
                    num_terminals = max(1, new_count)
                    
            # Only enforce minimum limit of 1
            num_terminals = max(1, num_terminals)
        except ValueError:
            print("Invalid input. Using 2 terminals.")
            num_terminals = 2
    
    # Get CSV file path
    csv_path = args.csv_path
    if not csv_path:
        csv_path = input("Enter the path to the CSV file: ")
    
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        return
    
    # Ask about background mode if not provided in args
    run_in_background = args.background
    if not args.background:
        background_choice = input("Run terminals in background mode? (y/n): ").lower()
        run_in_background = background_choice.startswith('y')
    
    # Create terminal directory
    terminal_dir = "terminal"
    create_directory(terminal_dir)
    
    # Count emails before dividing
    email_count = count_emails_in_csv(csv_path)
    if email_count == 0:
        print("No valid emails found in the CSV file.")
        return
        
    # Adjust terminal count if there are fewer emails than terminals
    if email_count < num_terminals:
        print(f"Warning: More terminals ({num_terminals}) requested than emails ({email_count}).")
        print(f"Adjusting to use {email_count} terminals instead.")
        num_terminals = email_count
    
    # Divide emails into chunks
    chunk_files = divide_emails(csv_path, num_terminals)
    if not chunk_files:
        return
    
    # Rest of the function remains unchanged
    # ...
    
    # Create shared output queue
    output_queue = []
    
    # Start terminal threads
    terminal_threads = []
    for i, chunk_file in enumerate(chunk_files):
        terminal_id = i + 1
        thread = threading.Thread(
            target=run_terminal, 
            args=(terminal_id, chunk_file, output_queue, run_in_background)
        )
        thread.daemon = True
        thread.start()
        terminal_threads.append(thread)
        
        # Add a small delay between starting terminals
        time.sleep(2)
    
    print(f"Started {len(terminal_threads)} terminals for email verification")
    if run_in_background:
        print("Terminals are running in background mode.")
    
    # Start display thread
    display_thread = threading.Thread(
        target=display_progress, 
        args=(output_queue, terminal_dir, len(chunk_files))
    )
    display_thread.daemon = True
    display_thread.start()
    
    # Wait for all terminal threads to complete
    for thread in terminal_threads:
        thread.join()
    
    # Wait for display thread to complete
    display_thread.join(timeout=60)
    
    print("All terminals have completed processing.")
    
    # Clean up all temporary files after completion
    cleanup_files(terminal_dir, len(chunk_files))

if __name__ == "__main__":
    main()