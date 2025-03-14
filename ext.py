import csv

def extract_microsoft_emails(input_file):
    microsoft_emails = []

    # Open the input CSV file
    with open(input_file, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Provider'] == 'Microsoft':
                microsoft_emails.append(row['Email'])

    # Join the emails with commas
    return ','.join(microsoft_emails)

# Example usage
input_file = 'c:\\Users\\abdoa\\Downloads\\verifier\\results\\verification_20250312131401\\valid_emails.csv'
microsoft_emails = extract_microsoft_emails(input_file)
print(microsoft_emails)