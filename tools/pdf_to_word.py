from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import os
import tempfile
from pathlib import Path
import shutil
from pdf2docx import Converter
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/convert")
async def convert_pdf_to_word(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    try:
        # Read the uploaded file content
        content = await file.read()
        logger.debug(f"Uploaded file size: {len(content)} bytes")
        
        # Save uploaded PDF
        pdf_path = os.path.join(temp_dir, file.filename)
        with open(pdf_path, "wb") as buffer:
            buffer.write(content)
        
        logger.debug(f"Saved PDF file to {pdf_path}")
        logger.debug(f"PDF file size: {os.path.getsize(pdf_path)} bytes")
        
        # Create output Word file path
        word_filename = Path(file.filename).stem + '.docx'
        word_path = os.path.join(temp_dir, word_filename)
        
        try:
            # Convert PDF to Word using pdf2docx
            cv = Converter(pdf_path)
            cv.convert(word_path)  # Convert PDF to Word
            cv.close()
            
            logger.debug(f"Conversion completed. Word file size: {os.path.getsize(word_path)} bytes")
            
        except Exception as conv_error:
            logger.error(f"Error during conversion: {str(conv_error)}")
            raise HTTPException(status_code=500, detail=f"Failed to convert PDF: {str(conv_error)}")
        
        # Verify the file exists and has content
        if not os.path.exists(word_path):
            raise HTTPException(status_code=500, detail="Failed to create Word document")
        
        file_size = os.path.getsize(word_path)
        logger.debug(f"Final Word file size: {file_size} bytes")
        
        if file_size < 1000:  # If file is less than 1KB
            raise HTTPException(status_code=500, detail="Generated Word file is too small, conversion may have failed")
        
        # Return the converted file
        return FileResponse(
            path=word_path,
            filename=word_filename,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{word_filename}"'}
        )
        
    except Exception as e:
        logger.error(f"Error during conversion: {str(e)}")
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up after response is sent
        def cleanup():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return cleanup 