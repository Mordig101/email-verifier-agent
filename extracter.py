import re

def extract_emails(file_path, output_file):
    # Define the email regex pattern
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    # Open the input file and output file
    with open(file_path, 'r', encoding='utf-8') as infile, open(output_file, 'w', encoding='utf-8') as outfile:
        for line in infile:
            # Split the line by commas and check each part for an email match
            for part in line.split(','):
                part = part.strip()
                if email_pattern.match(part):
                    outfile.write(part + '\n')

def main():
    # Prompt the user for the input file path
    input_file = input("Enter the path to the CSV or TXT file: ")
    
    # Prompt the user for the output file path
    output_file = input("Enter the path to save the extracted emails: ")
    
    # Extract emails and save them to the output file
    extract_emails(input_file, output_file)
    print(f"Emails extracted and saved to {output_file}")

if __name__ == "__main__":
    main()