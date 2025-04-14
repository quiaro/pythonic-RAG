#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Building the frontend...${NC}"
cd frontend
npm install
npm run build:prod
cd ..

echo -e "${BLUE}Creating combined app directory...${NC}"
mkdir -p dist
cp -r backend/* dist/
mkdir -p dist/frontend/build
cp -r frontend/build/* dist/frontend/build/

echo -e "${BLUE}Verifying frontend build directory structure...${NC}"
ls -la dist/frontend/build
ls -la dist/frontend/build/static

echo -e "${BLUE}Installing backend dependencies...${NC}"
cd dist
pip install -r requirements.txt

echo -e "${GREEN}Build complete!${NC}"
echo -e "${GREEN}To run the combined app:${NC}"
echo -e "cd dist"
echo -e "uvicorn main:app --host 0.0.0.0 --port 8000"

# Optionally, build Docker image
if [ "$1" == "--docker" ]; then
    echo -e "${BLUE}Building Docker image...${NC}"
    cd ..
    docker build -t pythonic-rag:latest .
    echo -e "${GREEN}Docker image built successfully!${NC}"
    echo -e "${GREEN}To run the Docker container:${NC}"
    echo -e "docker run -p 8000:8000 pythonic-rag:latest"
fi 