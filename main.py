from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from tools.rapid7_metrics import Rapid7Metrics
from tools.insightvm_processor import process_insightvm_files
from tools.query_converter import QueryConverter, QueryLanguage
from tools.pdf_to_word import router as pdf_to_word_router
from tools.device_comparator import compare_devices
import uvicorn
import os
from dotenv import load_dotenv
from typing import List
import shutil
from pathlib import Path
import io
import pandas as pd

# Load environment variables
print("Current working directory:", os.getcwd())
print("Looking for .env file...")
load_dotenv()
print("Environment variables loaded. RAPID7_API_KEY exists:", bool(os.getenv("RAPID7_API_KEY")))

def get_api_keys():
    api_keys = {}
    try:
        print("Reading .env file for API keys...")
        with open('.env', 'r') as file:
            for line in file:
                print(f"Reading line: {line.strip()}")
                if line.startswith('RAPID7_API_KEY_CLIENT'):
                    parts = line.strip().split('=')
                    if len(parts) == 2:
                        client_num = parts[0].replace('RAPID7_API_KEY_CLIENT', '')
                        # Get the corresponding API URL for this client
                        api_url = os.getenv(f'RAPID7_API_URL_CLIENT{client_num}', 'https://us3.api.insight.rapid7.com')
                        api_keys[f"Client {client_num}"] = {
                            'api_key': parts[1],
                            'api_url': api_url
                        }
                        print(f"Found API key for Client {client_num} with URL {api_url}")
    except Exception as e:
        print(f"Error reading .env file: {e}")
    
    print(f"Found {len(api_keys)} API keys: {list(api_keys.keys())}")
    return api_keys

# Get API keys
RAPID7_API_KEYS = get_api_keys()
print(f"Loaded API keys: {RAPID7_API_KEYS}")

app = FastAPI(title="Garden Tools")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include PDF to Word router
app.include_router(pdf_to_word_router, prefix="/pdf-to-word", tags=["pdf-to-word"])

# Templates
templates = Jinja2Templates(directory="templates")

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

query_converter = QueryConverter()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "Garden Tools"})

@app.get("/query-converter", response_class=HTMLResponse)
async def query_converter_form(request: Request):
    return templates.TemplateResponse(
        "query_converter.html",
        {"request": request, "title": "SIEM Query Converter"}
    )

@app.post("/query-converter", response_class=HTMLResponse)
async def convert_query(
    request: Request,
    source_language: str = Form(...),
    query: str = Form(...)
):
    try:
        source_lang = QueryLanguage(source_language.lower())
        results = query_converter.convert_to_all_languages(query, source_lang)
        print(f"Conversion results: {results}")  # Debug logging
        return templates.TemplateResponse(
            "query_converter.html",
            {
                "request": request,
                "title": "SIEM Query Converter",
                "results": results,
                "source_language": source_language,
                "query": query
            }
        )
    except Exception as e:
        print(f"Conversion error: {str(e)}")  # Debug logging
        return templates.TemplateResponse(
            "query_converter.html",
            {
                "request": request,
                "title": "SIEM Query Converter",
                "error": str(e),
                "source_language": source_language,
                "query": query
            }
        )

@app.get("/rapid7-metrics", response_class=HTMLResponse)
async def rapid7_metrics_form(request: Request):
    clients = list(RAPID7_API_KEYS.keys())
    print(f"Available clients for dropdown: {clients}")
    return templates.TemplateResponse(
        "rapid7_metrics.html",
        {
            "request": request,
            "title": "Rapid7 Metrics",
            "clients": clients
        }
    )

@app.post("/rapid7-metrics", response_class=HTMLResponse)
async def rapid7_metrics_calculate(
    request: Request,
    client: str = Form(...),
    start_date: str = Form(...),
    start_time: str = Form(...),
    end_date: str = Form(...),
    end_time: str = Form(...)
):
    client_config = RAPID7_API_KEYS.get(client)
    if not client_config:
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
                "clients": list(RAPID7_API_KEYS.keys()),
                "error": f"Configuration not found for {client}. Please check your .env file."
            }
        )

    try:
        # Combine date and time
        start_datetime = f"{start_date}T{start_time}:00Z"
        end_datetime = f"{end_date}T{end_time}:00Z"
        
        metrics = Rapid7Metrics(
            api_key=client_config['api_key'],
            api_url=client_config['api_url']
        )
        results = metrics.calculate_metrics(start_datetime, end_datetime)
        
        if "error" in results:
            return templates.TemplateResponse(
                "rapid7_metrics.html",
                {
                    "request": request,
                    "title": "Rapid7 Metrics",
                    "clients": list(RAPID7_API_KEYS.keys()),
                    "error": results["error"]
                }
            )
        
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
                "clients": list(RAPID7_API_KEYS.keys()),
                "selected_client": client,
                "results": results
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
                "clients": list(RAPID7_API_KEYS.keys()),
                "error": str(e)
            }
        )

@app.get("/insightvm-processor", response_class=HTMLResponse)
async def insightvm_processor_form(request: Request):
    return templates.TemplateResponse(
        "insightvm_processor.html",
        {"request": request, "title": "InsightVM Processor"}
    )

@app.post("/insightvm-processor")
async def insightvm_processor_upload(
    request: Request,
    insightvm_files: List[UploadFile] = File(...),
    inventory_file: UploadFile = File(...)
):
    session_dir = None
    try:
        # Create a temporary directory for this session
        session_dir = UPLOAD_DIR / "temp"
        if session_dir.exists():
            shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Save the inventory file
        inventory_path = session_dir / "inventory.csv"
        with open(inventory_path, "wb") as f:
            shutil.copyfileobj(inventory_file.file, f)
        
        # Save the InsightVM files
        insightvm_paths = []
        for file in insightvm_files:
            file_path = session_dir / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            insightvm_paths.append(str(file_path))
        
        # Process the files
        output_file = process_insightvm_files(
            insightvm_paths,
            str(inventory_path),
            str(session_dir)
        )
        
        # Verify the output file exists and is readable
        if not os.path.exists(output_file):
            raise Exception("Failed to generate the Excel file")
            
        # Read the file into memory
        with open(output_file, 'rb') as f:
            file_content = f.read()
            
        # Create a BytesIO object
        excel_io = io.BytesIO(file_content)
        excel_io.seek(0)
        
        # Return the file as a streaming response
        return StreamingResponse(
            excel_io,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                'Content-Disposition': 'attachment; filename="consolidated_results.xlsx"',
                'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'Content-Length': str(len(file_content))
            }
        )
        
    except Exception as e:
        error_message = f"Error processing files: {str(e)}"
        print(error_message)  # Log the error
        return templates.TemplateResponse(
            "insightvm_processor.html",
            {
                "request": request,
                "title": "InsightVM Processor",
                "error": error_message
            }
        )
    finally:
        # Clean up temporary files
        if session_dir and session_dir.exists():
            try:
                shutil.rmtree(session_dir)
            except Exception as e:
                print(f"Error cleaning up temporary files: {e}")

@app.get("/pdf-to-word", response_class=HTMLResponse)
async def pdf_to_word_form(request: Request):
    return templates.TemplateResponse(
        "pdf_to_word.html",
        {"request": request, "title": "PDF to Word Converter"}
    )

@app.get("/device-comparator", response_class=HTMLResponse)
async def device_comparator_form(request: Request):
    return templates.TemplateResponse(
        "device_comparator.html",
        {
            "request": request,
            "title": "Device Comparator"
        }
    )

@app.post("/device-comparator")
async def process_device_comparison(
    jc_file: UploadFile = File(...),
    sentinels_file: UploadFile = File(...),
    agents_file: UploadFile = File(...),
    mapping_file: UploadFile = File(...),
    ns_file: UploadFile = None,
    min_hours: int = Form(24),
    max_hours: int = Form(100)
):
    try:
        # Create temporary directory for files
        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)
        
        # Save uploaded files
        jc_path = temp_dir / "jc_devices.csv"
        sentinels_path = temp_dir / "sentinels.csv"
        agents_path = temp_dir / "agents.csv"
        mapping_path = temp_dir / "mapping.csv"
        ns_path = temp_dir / "ns_users.csv" if ns_file else None
        
        # Save required files
        with open(jc_path, "wb") as f:
            f.write(await jc_file.read())
        with open(sentinels_path, "wb") as f:
            f.write(await sentinels_file.read())
        with open(agents_path, "wb") as f:
            f.write(await agents_file.read())
        with open(mapping_path, "wb") as f:
            f.write(await mapping_file.read())
        
        # Save optional NS file if provided
        if ns_file:
            with open(ns_path, "wb") as f:
                f.write(await ns_file.read())
        
        # Process the files
        result_df = compare_devices(
            str(jc_path),
            str(sentinels_path),
            str(agents_path),
            str(mapping_path),
            str(ns_path) if ns_path else None,
            min_hours,
            max_hours
        )
        
        # Create response
        output = io.StringIO()
        result_df.to_csv(output, index=False)
        
        # Clean up temporary files
        shutil.rmtree(temp_dir)
        
        # Return the CSV file
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="device_comparison_results.csv"'
            }
        )
        
    except Exception as e:
        # Clean up temporary files in case of error
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 