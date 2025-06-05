import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ipaddress
import re
import sys
from typing import Dict, List, Optional, Union
from pathlib import Path

# Check for fuzzywuzzy or python-Levenshtein
try:
    from fuzzywuzzy import fuzz, process
except ImportError:
    print("Warning: fuzzywuzzy not installed. Attempting to install required packages...")
    import subprocess
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "fuzzywuzzy", "python-Levenshtein"])
        from fuzzywuzzy import fuzz, process
        print("Successfully installed fuzzywuzzy and python-Levenshtein")
    except Exception as e:
        print(f"Failed to install required packages: {e}")
        print("Please install manually with: pip install fuzzywuzzy python-Levenshtein")
        sys.exit(1)

def parse_date(date_str, format_str=None):
    """Parse date string to datetime object with various formats."""
    if pd.isna(date_str) or date_str == "N/A":
        return None
    
    # Convert to string if not already (handles potential numeric timestamps)
    if not isinstance(date_str, str):
        date_str = str(date_str)
    
    # Try specific format if provided
    if format_str:
        try:
            return datetime.strptime(date_str, format_str)
        except (ValueError, TypeError):
            pass
    
    # Try various formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",     # ISO format with timezone
        "%Y-%m-%dT%H:%M:%S.%f%z",   # ISO format with milliseconds and timezone
        "%Y-%m-%dT%H:%M:%S.%fZ",    # ISO format with Z
        "%Y-%m-%dT%H:%M:%S.%f",     # ISO format with milliseconds
        "%Y-%m-%dT%H:%M:%S",        # ISO format
        "%m/%d/%Y %H:%M",           # MM/DD/YYYY HH:MM
        "%Y-%m-%d %H:%M:%S",        # YYYY-MM-DD HH:MM:SS
        "%b %d, %Y %I:%M:%S %p"     # Apr 25, 2025 05:05:07 PM
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # If the datetime has a timezone, convert to naive by replacing with local time
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            continue
    
    # If all else fails, try to extract date components
    try:
        # Extract date parts using regex
        date_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
        if date_match:
            month, day, year = map(int, date_match.groups())
            time_match = re.search(r'(\d{1,2}):(\d{1,2})', date_str)
            if time_match:
                hour, minute = map(int, time_match.groups())
                return datetime(year, month, day, hour, minute)
            return datetime(year, month, day)
    except Exception:
        pass
    
    print(f"Warning: Could not parse date: {date_str}")
    return None

def is_ip_address(ip_str):
    """Check if the string is a valid IP address."""
    if pd.isna(ip_str) or not isinstance(ip_str, str):
        return False
    
    # Remove any surrounding quotes or spaces
    ip_str = ip_str.strip().strip("'").strip('"')
    
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False

def extract_ips(ip_str):
    """Extract IP addresses from string representation of list."""
    if pd.isna(ip_str):
        return []
    
    # Handle string representations of lists or arrays
    if isinstance(ip_str, str):
        # If it's a string representation of a list
        if ip_str.startswith('[') and ip_str.endswith(']'):
            # Split by commas and clean each element
            items = ip_str.strip('[]').split(',')
            ips = []
            for item in items:
                # Extract string between quotes if present
                match = re.search(r"'([^']*)'", item)
                if match:
                    ip = match.group(1)
                    if is_ip_address(ip):
                        ips.append(ip)
            return ips
    
    # If it's just a single IP
    if is_ip_address(ip_str):
        return [ip_str]
    
    return []

def format_datetime(dt):
    """Safely format datetime objects, handling NaT values."""
    if pd.isna(dt) or dt is None:
        return 'Unknown'
    try:
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return 'Unknown'

def load_data(filename):
    """Load data from either CSV or Excel file."""
    try:
        if filename.endswith('.csv'):
            return pd.read_csv(filename)
        elif filename.endswith(('.xlsx', '.xls')):
            return pd.read_excel(filename)
        else:
            print(f"Unsupported file format for {filename}. Please use CSV or Excel files.")
            return None
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        try:
            # Try with different encoding if standard fails
            if filename.endswith('.csv'):
                return pd.read_csv(filename, encoding='latin1')
            else:
                return pd.read_excel(filename, encoding='latin1')
        except Exception as e2:
            print(f"Failed to load {filename} with alternative encoding: {e2}")
            return None

def compare_devices(jc_file, sentinels_file, agents_file, mapping_file, ns_file=None, hours_min=24, hours_max=100):
    """
    Compare devices across different inventory systems and identify those 
    that haven't reported in the specified time range.
    """
    # Current time as reference point - make sure it's timezone-naive
    current_time = datetime.now().replace(tzinfo=None)
    min_time_threshold = current_time - timedelta(hours=hours_max)
    max_time_threshold = current_time - timedelta(hours=hours_min)
    
    # Read files
    jc_df = load_data(jc_file)
    sentinels_df = load_data(sentinels_file)
    agents_df = load_data(agents_file)
    mapping_df = load_data(mapping_file)
    
    # Load NS_List file if provided
    ns_df = None
    if ns_file:
        ns_df = load_data(ns_file)
        if ns_df is None:
            print(f"Warning: Could not load NS List file {ns_file}. NS status will be marked as 'Unknown'.")
    
    # Check if any required file failed to load
    if jc_df is None or sentinels_df is None or agents_df is None or mapping_df is None:
        print("Failed to load one or more required files. Exiting.")
        return pd.DataFrame()
    
    # Clean up dataframes
    
    # Process JumpCloud data
    jc_df = jc_df.fillna('N/A')
    # Extract hostname from JC data (it's in different columns depending on the file)
    if 'hostname' in jc_df.columns:
        jc_df['DeviceName'] = jc_df['hostname']
    elif 'displayName' in jc_df.columns:
        jc_df['DeviceName'] = jc_df['displayName']
    else:
        print("Warning: Couldn't find hostname column in JumpCloud data")
        jc_df['DeviceName'] = 'Unknown'
    
    # Ensure serial number column exists
    if 'serialNumber' in jc_df.columns:
        jc_df['SerialNumber'] = jc_df['serialNumber']
    else:
        print("Warning: No serial number column found in JumpCloud data")
        jc_df['SerialNumber'] = 'Unknown'
    
    # Process lastContact date
    jc_df['JC_LastContact'] = jc_df['lastContact'].apply(lambda x: parse_date(x) if not pd.isna(x) else None)
    
    # Extract IP addresses
    jc_ip_cols = [col for col in jc_df.columns if 'ip' in col.lower() or 'address' in col.lower()]
    if 'remoteIP' in jc_df.columns:
        jc_df['IPAddresses'] = jc_df['remoteIP'].apply(extract_ips)
    elif len(jc_ip_cols) > 0:
        # Use the first IP column found
        jc_df['IPAddresses'] = jc_df[jc_ip_cols[0]].apply(extract_ips)
    else:
        # Try to extract IPs from networkInterfaces
        if 'networkInterfaces' in jc_df.columns:
            jc_df['IPAddresses'] = jc_df['networkInterfaces'].apply(
                lambda x: re.findall(r'address:([^,}]+)', str(x)) if not pd.isna(x) else []
            )
        else:
            jc_df['IPAddresses'] = [[]] * len(jc_df)
    
    # Process Sentinels data
    sentinels_df = sentinels_df.fillna('N/A')
    
    # Ensure consistent column naming
    if 'Serial Number' in sentinels_df.columns:
        sentinels_df['SerialNumber'] = sentinels_df['Serial Number']
    else:
        print("Warning: No Serial Number column found in Sentinels data")
        sentinels_df['SerialNumber'] = 'Unknown'
    
    # Process Last Active date
    if 'Last Active' in sentinels_df.columns:
        sentinels_df['Sentinel_LastActive'] = sentinels_df['Last Active'].apply(
            lambda x: parse_date(x) if not pd.isna(x) and x != 'N/A' else None
        )
    else:
        print("Warning: No Last Active column found in Sentinels data")
        sentinels_df['Sentinel_LastActive'] = None
    
    # Extract endpoint name
    if 'Endpoint Name' in sentinels_df.columns:
        sentinels_df['EndpointName'] = sentinels_df['Endpoint Name']
    else:
        sentinels_df['EndpointName'] = 'Unknown'
    
    # Process agents data
    agents_df = agents_df.fillna('N/A')
    
    # Process Last Seen date
    if 'Last Seen' in agents_df.columns:
        agents_df['Agent_LastSeen'] = agents_df['Last Seen'].apply(lambda x: parse_date(x) if not pd.isna(x) and x != 'N/A' else None)
    else:
        print("Warning: No Last Seen column found in Agents data")
        agents_df['Agent_LastSeen'] = None
    
    # Get IP addresses from agents
    if 'Public IP Address' in agents_df.columns:
        agents_df['PublicIP'] = agents_df['Public IP Address']
    elif 'IP Address (Primary)' in agents_df.columns:
        agents_df['PublicIP'] = agents_df['IP Address (Primary)']
    else:
        print("Warning: No IP address column found in Agents data")
        agents_df['PublicIP'] = 'Unknown'
    
    # Process mapping data
    mapping_df = mapping_df.fillna('N/A')
    # Convert hostname to lowercase for case-insensitive matching
    if 'HostName' in mapping_df.columns:
        mapping_df['HostName_lower'] = mapping_df['HostName'].str.lower()
    else:
        print("Warning: No HostName column found in mapping file")
        mapping_df['HostName_lower'] = 'Unknown'
    
    # Create result dataframe
    result = []
    
    # Match JumpCloud to Sentinels based on Serial Number
    for index, jc_row in jc_df.iterrows():
        # Convert row to dictionary to avoid pandas Series issues in boolean contexts
        jc_dict = jc_row.to_dict()
        
        # Find matching sentinel record
        sentinel_match = sentinels_df[sentinels_df['SerialNumber'] == jc_dict['SerialNumber']]
        
        # Initialize with JumpCloud data
        device_data = {
            'DeviceName': jc_dict['DeviceName'],
            'DisplayName': jc_dict['DeviceName'],  # Default to DeviceName if no mapping found
            'JC_SerialNumber': jc_dict['SerialNumber'],
            'JC_LastContact': jc_dict['JC_LastContact'],
            'Sentinel_SerialNumber': 'Not Found',
            'Sentinel_LastActive': None,
            'Agent_Hostname': 'Not Found',
            'Agent_LastSeen': None,
            'Match_Method': [],
            'Not_Reported_Hours': {},
            'Email': 'Not Found',  # Added for NS lookup
            'NS': 'Unknown'        # Added for NS status
        }
        
        # Look for mapping based on hostname (case insensitive)
        device_hostname = jc_dict['DeviceName'].lower()
        mapping_match = mapping_df[mapping_df['HostName_lower'] == device_hostname]
        
        if not mapping_match.empty:
            device_data['DisplayName'] = mapping_match.iloc[0]['displayname']
            
            # Extract email from mapping if available
            if 'email' in mapping_match.columns:
                device_data['Email'] = mapping_match.iloc[0]['email']
            
        # Add Sentinel data if found
        if not sentinel_match.empty:
            sentinel_dict = sentinel_match.iloc[0].to_dict()
            device_data['Sentinel_SerialNumber'] = sentinel_dict['SerialNumber']
            device_data['Sentinel_LastActive'] = sentinel_dict['Sentinel_LastActive']
            device_data['Match_Method'].append('Serial Number')
        
        # Find best match in agents using fuzzywuzzy on hostname
        best_match = None
        best_score = 0
        
        # Try to match by hostname first
        if 'Hostname' in agents_df.columns:  
            hostname_matches = []
            for _, agent_row in agents_df.iterrows():
                agent_dict = agent_row.to_dict()
                score = fuzz.ratio(jc_dict['DeviceName'].lower(), agent_dict['Hostname'].lower())
                if score > 70:  # Threshold for fuzzy matching
                    hostname_matches.append((agent_dict, score))
            
            # Sort by score descending
            hostname_matches.sort(key=lambda x: x[1], reverse=True)
            
            if hostname_matches:
                best_match = hostname_matches[0][0]
                best_score = hostname_matches[0][1]
                device_data['Match_Method'].append(f'Hostname Fuzzy ({best_score}%)')
        
        # If no good hostname match, try IP matching
        # Convert IPAddresses to list if needed
        ip_addresses = jc_dict['IPAddresses']
        if isinstance(ip_addresses, pd.Series):
            ip_addresses = ip_addresses.tolist()
            
        # Ensure ip_addresses is a list and not None
        if ip_addresses is None:
            ip_addresses = []
        
        if best_match is None and ip_addresses:
            for _, agent_row in agents_df.iterrows():
                agent_dict = agent_row.to_dict()
                public_ip = agent_dict.get('PublicIP', '')
                
                if public_ip and any(public_ip == ip for ip in ip_addresses):
                    best_match = agent_dict
                    device_data['Match_Method'].append('IP Address')
                    break
        
        # Add agent data if found
        if best_match is not None:
            device_data['Agent_Hostname'] = best_match.get('Hostname', 'Unknown')
            device_data['Agent_LastSeen'] = best_match.get('Agent_LastSeen')
        
        # Calculate hours since last contact for each system
        contact_times = {
            'JumpCloud': jc_dict['JC_LastContact'],
            'Sentinel': device_data['Sentinel_LastActive'],
            'Agent': device_data['Agent_LastSeen']
        }
        
        not_reported_hours = {}
        is_in_range = False
        sources_in_range = []
        
        for source, contact_time in contact_times.items():
            if contact_time is not None:
                # Ensure both times are timezone-naive for comparison
                if contact_time.tzinfo is not None:
                    contact_time = contact_time.replace(tzinfo=None)
                
                hours_since = (current_time - contact_time).total_seconds() / 3600
                not_reported_hours[source] = hours_since
                # Check if hours fall within our range
                if min_time_threshold <= contact_time <= max_time_threshold:
                    is_in_range = True
                    sources_in_range.append(source)
            else:
                not_reported_hours[source] = "Unknown"
        
        device_data['Not_Reported_Hours'] = not_reported_hours
        device_data['Sources_Not_Reporting'] = sources_in_range
        
        # Check NS status if we have a mapping and NS file
        if ns_df is not None and device_data['Email'] != 'Not Found':
            # Look for the email in NS file
            if 'User' in ns_df.columns:
                ns_match = ns_df[ns_df['User'].str.lower() == device_data['Email'].lower()]
                if not ns_match.empty:
                    device_data['NS'] = 'PRESENT'
                else:
                    device_data['NS'] = 'ABSENT'
        
        # Only add to results if device has not reported in the specified time range
        if is_in_range:
            result.append(device_data)
    
    # Convert to DataFrame
    if result:
        result_df = pd.DataFrame(result)
        
        # Create columns for each source status
        result_df['Status'] = result_df.apply(
            lambda row: ', '.join([f"{source}" for source in row['Sources_Not_Reporting']]), axis=1
        )
        
        # Format the output for better readability - using our safe format_datetime function
        result_df['JC_LastContact'] = result_df['JC_LastContact'].apply(format_datetime)
        result_df['Sentinel_LastActive'] = result_df['Sentinel_LastActive'].apply(format_datetime)
        result_df['Agent_LastSeen'] = result_df['Agent_LastSeen'].apply(format_datetime)
        
        # Format hours since last contact
        result_df['Not_Reported_Summary'] = result_df['Not_Reported_Hours'].apply(
            lambda x: ', '.join([f"{k}: {v:.1f}h" if isinstance(v, (int, float)) else f"{k}: {v}" for k, v in x.items()])
        )
        
        # Sort by display name
        result_df = result_df.sort_values('DisplayName')
        
        # Select and reorder columns for display as requested
        display_columns = [
            'DisplayName', 
            'Status',
            'JC_LastContact', 
            'Sentinel_LastActive', 
            'Agent_LastSeen',
            'Not_Reported_Summary',
            'NS'  # Added NS status column
        ]
        
        return result_df[display_columns]
    else:
        # Return an empty DataFrame with the expected columns
        return pd.DataFrame(columns=['DisplayName', 'Status', 'JC_LastContact', 
                                     'Sentinel_LastActive', 'Agent_LastSeen',
                                     'Not_Reported_Summary', 'NS']) 