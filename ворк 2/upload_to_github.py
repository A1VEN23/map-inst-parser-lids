#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Upload files to GitHub repository via GitHub API.
Requires GitHub Personal Access Token.
"""

import requests
import base64
import json
import os
from pathlib import Path

# GitHub repository info
REPO_OWNER = "A1VEN23"
REPO_NAME = "map-inst-parser-lids"
BASE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

def get_files_to_upload(folder_path):
    """Get all files to upload from folder."""
    files = {}
    folder = Path(folder_path)
    
    for file_path in folder.rglob('*'):
        if file_path.is_file() and not file_path.name.startswith('.') and file_path.name != 'upload_to_github.py':
            # Get relative path from folder
            rel_path = file_path.relative_to(folder)
            with open(file_path, 'rb') as f:
                content = f.read()
            files[str(rel_path).replace('\\', '/')] = content
    
    return files

def upload_file_to_github(file_path, content, token, message="Initial commit"):
    """Upload single file to GitHub."""
    url = f"{BASE_URL}/contents/{file_path}"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    # Encode content in base64
    content_b64 = base64.b64encode(content).decode('utf-8')
    
    data = {
        "message": f"{message}: {file_path}",
        "content": content_b64
    }
    
    # Check if file already exists
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            # File exists, get sha for update
            existing_data = response.json()
            data["sha"] = existing_data["sha"]
    except:
        pass
    
    # Create or update file
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code in [201, 200]:
        print(f"Uploaded: {file_path}")
        return True
    else:
        print(f"Failed to upload {file_path}: {response.status_code}")
        print(f"Response: {response.text}")
        return False

def upload_all_files(folder_path, token):
    """Upload all files to GitHub."""
    files = get_files_to_upload(folder_path)
    
    if not files:
        print("No files to upload")
        return
    
    print(f"Found {len(files)} files to upload")
    
    success_count = 0
    for file_path, content in files.items():
        if upload_file_to_github(file_path, content, token):
            success_count += 1
    
    print(f"\nSuccessfully uploaded {success_count}/{len(files)} files")
    print(f"Repository: https://github.com/{REPO_OWNER}/{REPO_NAME}")

if __name__ == "__main__":
    print("GitHub Uploader for Lead Generation Project")
    print("=" * 50)
    
    # Get GitHub token
    token = input("Enter your GitHub Personal Access Token: ").strip()
    
    if not token:
        print("Token is required")
        exit(1)
    
    # Upload files
    current_folder = "."
    upload_all_files(current_folder, token)
    
    print("\nUpload complete!")
    print(f"Repository: https://github.com/{REPO_OWNER}/{REPO_NAME}")
