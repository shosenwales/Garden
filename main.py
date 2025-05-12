from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from tools.rapid7_metrics import Rapid7Metrics
from tools.insightvm_processor import process_insightvm_files
from tools.query_converter import QueryConverter, QueryLanguage
from tools.pdf_to_word import router as pdf_to_word_router
import uvicorn
import os
from dotenv import load_dotenv
from typing import List
import shutil
from pathlib import Path
import io
import pandas as pd

# Load environment variables
load_dotenv()

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
    return templates.TemplateResponse(
        "rapid7_metrics.html",
        {"request": request, "title": "Rapid7 Metrics"}
    )

@app.post("/rapid7-metrics", response_class=HTMLResponse)
async def rapid7_metrics_calculate(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...)
):
    api_key = os.getenv("RAPID7_API_KEY")
    if not api_key:
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
                "error": "Rapid7 API key not found in environment variables. Please set RAPID7_API_KEY in your .env file."
            }
        )

    try:
        metrics = Rapid7Metrics(api_key)
        results = metrics.calculate_metrics(start_date, end_date)
        
        if "error" in results:
            return templates.TemplateResponse(
                "rapid7_metrics.html",
                {
                    "request": request,
                    "title": "Rapid7 Metrics",
                    "error": results["error"]
                }
            )
        
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
                "results": results
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "rapid7_metrics.html",
            {
                "request": request,
                "title": "Rapid7 Metrics",
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 