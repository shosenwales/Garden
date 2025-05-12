import json
import subprocess
from datetime import datetime
from typing import Dict, List, Tuple, Optional

class Rapid7Metrics:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.investigation_url = "https://us3.api.insight.rapid7.com/idr/v1/investigations"
        self.comments_url = "https://us3.api.insight.rapid7.com/idr/v1/comments?target="

    def fetch_investigations(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetches investigations from Rapid7 API based on date range."""
        start_time = f"{start_date}T00:00:00Z"
        end_time = f"{end_date}T23:59:00Z"
        
        all_investigations = []
        index = 0
        size = 100  # Maximum allowed by API
        
        while True:
            url = f"{self.investigation_url}?index={index}&size={size}&statuses=OPEN,INVESTIGATING,CLOSED&start_time={start_time}&end_time={end_time}"
            command = f'curl -s -H "X-Api-Key: {self.api_key}" -H "Content-Type: application/json" "{url}"'
            
            response = subprocess.run(command, shell=True, capture_output=True, text=True)

            if response.returncode != 0:
                raise Exception(f"Error: Curl command failed with return code {response.returncode}")

            try:
                data = json.loads(response.stdout)
                investigations = data.get("data", [])
                
                if not investigations:  # No more investigations to fetch
                    break
                    
                all_investigations.extend(investigations)
                
                # Check if we've received fewer items than requested, indicating we're at the end
                if len(investigations) < size:
                    break
                    
                index += size  # Move to next page
                
            except json.JSONDecodeError:
                raise Exception("Error: Unable to parse JSON from investigations API.")

        return all_investigations

    def fetch_comment_times(self, rrn: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetches first and last comment timestamps for an investigation."""
        url = f"{self.comments_url}{rrn}"
        command = f'curl -s -H "X-Api-Key: {self.api_key}" -H "Content-Type: application/json" "{url}"'
        
        response = subprocess.run(command, shell=True, capture_output=True, text=True)

        if response.returncode != 0:
            return None, None

        try:
            data = json.loads(response.stdout)
            comments = data.get("data", [])
            valid_comments = [c for c in comments if 'created_time' in c]

            if not valid_comments or len(valid_comments) < 2:
                return None, None

            return valid_comments[0]['created_time'], valid_comments[1]['created_time']
        
        except json.JSONDecodeError:
            return None, None

    @staticmethod
    def calculate_time_difference(start_time: str, end_time: str) -> Optional[float]:
        """Calculates time difference in minutes."""
        if not start_time or not end_time:
            return None

        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        return (end_dt - start_dt).total_seconds() / 60

    @staticmethod
    def format_time(minutes: Optional[float]) -> str:
        """Formats time in minutes and seconds (e.g., '10 min 15 sec')."""
        if minutes is None:
            return "N/A"
        
        mins = int(minutes)
        secs = round((minutes - mins) * 60)
        return f"{mins} min {secs} sec"

    def calculate_metrics(self, start_date: str, end_date: str) -> Dict:
        """Calculate MTTD and MTTR metrics for the given date range."""
        investigations = self.fetch_investigations(start_date, end_date)
        investigation_count = len(investigations)

        if not investigations:
            return {
                "error": "No investigations found for the specified date range."
            }

        total_mttd = 0
        total_mttr = 0
        count_mttd = 0
        count_mttr = 0
        
        for inv in investigations:
            rrn = inv.get("rrn")
            created_time = inv.get("created_time")

            if not rrn or not created_time:
                continue

            first_comment_time, last_comment_time = self.fetch_comment_times(rrn)

            mttd = self.calculate_time_difference(created_time, first_comment_time)
            mttr = self.calculate_time_difference(created_time, last_comment_time)

            if mttd is not None:
                total_mttd += mttd
                count_mttd += 1

            if mttr is not None:
                total_mttr += mttr
                count_mttr += 1

        overall_mttd = total_mttd / count_mttd if count_mttd > 0 else None
        overall_mttr = total_mttr / count_mttr if count_mttr > 0 else None

        return {
            "date_range": f"{start_date} to {end_date}",
            "total_investigations": investigation_count,
            "mttd": self.format_time(overall_mttd),
            "mttr": self.format_time(overall_mttr),
            "raw_mttd": overall_mttd,
            "raw_mttr": overall_mttr
        } 