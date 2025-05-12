import csv
import pandas as pd
import os
from fuzzywuzzy import fuzz
from typing import List, Dict, Tuple, Optional
from pathlib import Path

def sanitize_sheet_name(sheet_name: str) -> str:
    """
    Sanitizes sheet names to remove any invalid characters for Excel.
    """
    invalid_chars = ['\\', '/', '?', '*', '[', ']', ':', ' ']
    for char in invalid_chars:
        sheet_name = sheet_name.replace(char, '_')
    return sheet_name[:31]

def improved_fuzzy_match_hostname(hostname: str, enrichment_data: Dict, threshold: int = 65) -> Tuple[Optional[str], float]:
    """
    Enhanced fuzzy matching that considers both token set ratio and partial ratio
    to better match hostnames with similar words, with priority for owner name matching.
    """
    best_match = None
    best_score = 0
    
    # Clean and normalize the input hostname
    hostname = hostname.lower().strip()
    
    # Extract owner name if possible (assuming format like "owner-device.domain")
    hostname_parts = hostname.split('-')[0] if '-' in hostname else hostname
    
    for enrich_hostname in enrichment_data.keys():
        # Clean and normalize the enrichment hostname
        enrich_hostname_clean = enrich_hostname.lower().strip()
        
        # Extract owner name from enrichment hostname if possible
        enrich_hostname_parts = enrich_hostname_clean.split('-')[0] if '-' in enrich_hostname_clean else ""
        enrich_hostname_parts_alt = enrich_hostname_clean.split('s-')[0] + 's' if 's-' in enrich_hostname_clean else ""
        
        # Calculate different types of fuzzy ratios
        token_set_ratio = fuzz.token_set_ratio(hostname, enrich_hostname_clean)
        partial_ratio = fuzz.partial_ratio(hostname, enrich_hostname_clean)
        token_sort_ratio = fuzz.token_sort_ratio(hostname, enrich_hostname_clean)
        
        # Calculate owner name similarity (higher weight for owner matching)
        owner_match_score = 0
        if hostname_parts and (enrich_hostname_parts or enrich_hostname_parts_alt):
            owner_ratio1 = fuzz.ratio(hostname_parts, enrich_hostname_parts)
            owner_ratio2 = fuzz.ratio(hostname_parts, enrich_hostname_parts_alt)
            owner_match_score = max(owner_ratio1, owner_ratio2)
        
        # Use a weighted average of different ratios with higher weight for owner matching
        combined_score = (token_set_ratio * 0.25 +     # Weight for word matching regardless of order
                          partial_ratio * 0.25 +       # Weight for partial string matching
                          token_sort_ratio * 0.15 +    # Weight for sorted word matching
                          owner_match_score * 0.35)    # Weight for owner name matching
        
        # Update best match if this score is higher
        if combined_score > best_score and combined_score >= threshold:
            best_score = combined_score
            best_match = enrich_hostname
            
    return best_match, best_score

def process_insightvm_file(insightvm_csv: str, enrichment_data: Dict) -> Tuple[List[Dict], List[str]]:
    """
    Process each InsightVM file, match hostnames using enhanced fuzzy matching, and extract relevant data.
    """
    matched_assets = []
    unmatched_assets = []

    with open(insightvm_csv, "r", encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        for row in reader:
            hostname = row.get("Asset Name")
            if hostname:
                matched_hostname, score = improved_fuzzy_match_hostname(hostname, enrichment_data)

                if matched_hostname:
                    matched_data = {
                        "Hostname": hostname,
                        "Asset Name": enrichment_data[matched_hostname]["displayName"],
                        "Serial Number": enrichment_data[matched_hostname]["serialNumber"]
                    }
                    matched_assets.append(matched_data)
                else:
                    unmatched_assets.append(hostname)
            else:
                print(f"Warning: Missing 'Asset Name' in row {row}")

    return matched_assets, unmatched_assets

def process_insightvm_files(insightvm_csv_files: List[str], inventory_csv: str, output_directory: str) -> str:
    """
    Main function to process multiple InsightVM files and create a consolidated Excel report.
    
    Args:
        insightvm_csv_files: List of paths to InsightVM CSV files
        inventory_csv: Path to the asset inventory CSV file
        output_directory: Directory to save the consolidated Excel file
        
    Returns:
        str: Path to the generated Excel file
    """
    # Ensure output directory exists
    Path(output_directory).mkdir(parents=True, exist_ok=True)

    try:
        with open(inventory_csv, "r", encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            enrichment_data = {row["hostname"]: {
                "displayName": row["displayName"],
                "serialNumber": row["serialNumber"]
            } for row in reader}
    except Exception as e:
        raise Exception(f"Error reading the inventory file: {e}")

    output_file = os.path.join(output_directory, 'consolidated_results.xlsx')
    
    # Create a new Excel writer
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        all_unmatched = {}

        for insightvm_csv in insightvm_csv_files:
            print(f"Processing {insightvm_csv}...")

            try:
                matched_assets, unmatched_assets = process_insightvm_file(
                    insightvm_csv, enrichment_data)

                # Create DataFrame for the matched assets
                matched_df = pd.DataFrame(matched_assets)

                # Generate sheet name from the input file name
                sheet_name = sanitize_sheet_name(os.path.basename(insightvm_csv).split('.')[0])

                # Write the DataFrame to a new sheet in the consolidated workbook
                matched_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # Store unmatched assets
                if unmatched_assets:
                    all_unmatched[sheet_name] = unmatched_assets
                    print(f"\nUnmatched hostnames in {insightvm_csv}:")
                    for hostname in unmatched_assets:
                        print(f"  - {hostname}")

            except Exception as e:
                print(f"Error processing file {insightvm_csv}: {e}")

        # Create a summary sheet for unmatched assets
        if all_unmatched:
            summary_data = []
            for file_name, unmatched in all_unmatched.items():
                for hostname in unmatched:
                    summary_data.append({
                        "Source File": file_name,
                        "Unmatched Hostname": hostname
                    })
            unmatched_df = pd.DataFrame(summary_data)
            unmatched_df.to_excel(writer, sheet_name='Unmatched_Assets', index=False)

    # Verify the file exists before returning
    if not os.path.exists(output_file):
        raise Exception("Failed to create the Excel file")
        
    return output_file 