from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import tempfile
import shutil
import uuid
from typing import Dict, List, Optional
import asyncio
import uvicorn
from pydantic import BaseModel
import pathlib

# Import utility modules from aimakerspace
import sys
sys.path.append('..')
from aimakerspace.text_utils import CharacterTextSplitter, TextFileLoader, PDFLoader
from aimakerspace.openai_utils.prompts import (
    UserRolePrompt,
    SystemRolePrompt,
)
from aimakerspace.openai_utils.chatmodel import ChatOpenAI
from aimakerspace.vectordatabase import VectorDatabase


# Determine the frontend build directory 
# If in Docker, the frontend build is at /app/frontend/build
# If running locally, use relative path ../frontend/build
FRONTEND_BUILD_DIR = "/app/frontend/build" if os.path.exists("/app/frontend/build") else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "build")
FRONTEND_STATIC_DIR = os.path.join(FRONTEND_BUILD_DIR, "static")
FRONTEND_INDEX_HTML = os.path.join(FRONTEND_BUILD_DIR, "index.html")


app = FastAPI(title="RAG API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, specify the actual origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
sessions = {}  # Store user sessions
text_splitter = CharacterTextSplitter()

# Define the system and user prompts
system_template = """
Use the following context to answer a users question. If you cannot find the answer in the context, say you don't know the answer.
"""
system_role_prompt = SystemRolePrompt(system_template)

user_prompt_template = """
Context:
{context}

Question:
{question}
"""
user_role_prompt = UserRolePrompt(user_prompt_template)


class RetrievalAugmentedQAPipeline:
    def __init__(self, llm: ChatOpenAI, vector_db_retriever: VectorDatabase) -> None:
        self.llm = llm
        self.vector_db_retriever = vector_db_retriever

    async def arun_pipeline(self, user_query: str):
        context_list = self.vector_db_retriever.search_by_text(user_query, k=4)

        context_prompt = ""
        for context in context_list:
            context_prompt += context[0] + "\n"

        formatted_system_prompt = system_role_prompt.create_message()
        formatted_user_prompt = user_role_prompt.create_message(question=user_query, context=context_prompt)

        async def generate_response():
            async for chunk in self.llm.astream([formatted_system_prompt, formatted_user_prompt]):
                yield chunk

        return {"response": generate_response(), "context": context_list}


def process_file(file_path: str, file_name: str):
    # Create appropriate loader based on file extension
    if file_name.lower().endswith('.pdf'):
        loader = PDFLoader(file_path)
    else:
        loader = TextFileLoader(file_path)
        
    # Load and process the documents
    documents = loader.load_documents()
    return text_splitter.split_texts(documents)


class QueryRequest(BaseModel):
    session_id: str
    query: str


@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    # Validate file type
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ['.txt', '.pdf']:
        raise HTTPException(status_code=400, detail="Only .txt and .pdf files are supported")
    
    # Create a unique session ID
    session_id = str(uuid.uuid4())
    
    # Initialize the session with processing status
    sessions[session_id] = {
        "status": "processing",
        "file_name": file.filename
    }
    
    # Create a temporary file with the correct extension
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
        # Copy the uploaded file content to the temporary file
        shutil.copyfileobj(file.file, temp_file)
        temp_file_path = temp_file.name
    
    # Process the file in the background
    background_tasks.add_task(process_file_and_setup_session, session_id, temp_file_path, file.filename)
    
    return {"session_id": session_id, "status": "processing"}


async def process_file_and_setup_session(session_id: str, file_path: str, file_name: str):
    try:
        # Process the file
        texts = process_file(file_path, file_name)
        
        # Create a vector database
        vector_db = VectorDatabase()
        vector_db = await vector_db.abuild_from_list(texts)
        
        # Create the chat model
        chat_openai = ChatOpenAI()
        
        # Create the retrieval pipeline
        retrieval_augmented_qa_pipeline = RetrievalAugmentedQAPipeline(
            vector_db_retriever=vector_db,
            llm=chat_openai
        )
        
        # Update the session rather than replacing it
        sessions[session_id].update({
            "pipeline": retrieval_augmented_qa_pipeline,
            "file_name": file_name,
            "status": "ready"
        })
    except Exception as e:
        # Update the session with error information
        sessions[session_id].update({
            "status": "error",
            "error": str(e)
        })
    finally:
        # Clean up the temporary file
        try:
            os.unlink(file_path)
        except Exception:
            pass


@app.get("/session/{session_id}")
async def get_session_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "status": sessions[session_id]["status"],
        "file_name": sessions[session_id].get("file_name") if sessions[session_id]["status"] == "ready" else None,
        "error": sessions[session_id].get("error") if sessions[session_id]["status"] == "error" else None
    }


@app.post("/query")
async def query(request: QueryRequest):
    session_id = request.session_id
    query_text = request.query
    
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if sessions[session_id]["status"] != "ready":
        raise HTTPException(status_code=400, detail=f"Session is not ready: {sessions[session_id]['status']}")
    
    pipeline = sessions[session_id]["pipeline"]
    
    try:
        # Run the pipeline
        result = await pipeline.arun_pipeline(query_text)
        
        # Create a streaming response
        async def stream_response():
            try:
                async for chunk in result["response"]:
                    # Ensure each chunk is properly encoded and flushed
                    yield chunk
            except Exception as e:
                # Log the error but don't raise it to avoid breaking the stream
                print(f"Error in streaming response: {str(e)}")
                yield f"\n\nError during response generation: {str(e)}"
        
        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",  # Disable buffering for Nginx
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream"
            }
        )
    except Exception as e:
        # Handle exceptions during pipeline execution
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del sessions[session_id]
    return {"status": "deleted"}


# Mount the frontend build folder
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(FRONTEND_INDEX_HTML)

# Catch-all route to serve React Router paths
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_react_app(full_path: str):
    # If the path is an API endpoint, skip this handler
    if full_path.startswith("upload") or full_path.startswith("query") or full_path.startswith("session"):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check if a static file exists in the build folder
    static_file_path = os.path.join(FRONTEND_BUILD_DIR, full_path)
    if os.path.isfile(static_file_path):
        return FileResponse(static_file_path)
    
    # Otherwise, serve the index.html for client-side routing
    return FileResponse(FRONTEND_INDEX_HTML)

# Mount static files (JavaScript, CSS, images)
app.mount("/static", StaticFiles(directory=FRONTEND_STATIC_DIR), name="static")

# Main entry point
if __name__ == "__main__":
    # Make sure the frontend build folder exists
    if not os.path.exists("../frontend/build"):
        print("Frontend build directory not found. Building frontend...")
        # Build the frontend
        os.chdir("../frontend")
        os.system("npm install")
        os.system("npm run build")
        os.chdir("../backend")

    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=True) 