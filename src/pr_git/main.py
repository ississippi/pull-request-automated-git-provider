from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import os
import boto3
import requests
from datetime import datetime
from dateutil import tz

app = FastAPI()

# AWS SSM Client for secrets
ssm = boto3.client('ssm')

def get_parameter(name: str) -> str:
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response['Parameter']['Value']

GIT_API_KEY = get_parameter("/prreview/GIT_API_KEY")
if not GIT_API_KEY:
    raise RuntimeError("Missing GitHub API Key")

SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cs', '.cpp', '.c', '.go', '.rb'}

# Shared GitHub headers
def auth_headers(custom_accept=None):
    return {
        "Authorization": f"token {GIT_API_KEY}",
        "Accept": custom_accept or "application/vnd.github.v3+json"
    }

class ReviewRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int
    decision: str
    review: str

@app.get("/pull-requests/")
def get_pull_requests(owner: str, repo: str, state: str = 'open'):
    pulls_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    params = {"state": state, "per_page": 5}
    response = requests.get(pulls_url, headers=auth_headers(), params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()

@app.get("/pull-request/{owner}/{repo}/{pr_number}/files")
def get_pr_files(owner: str, repo: str, pr_number: int):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    response = requests.get(url, headers=auth_headers())
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()

@app.get("/pull-request/{owner}/{repo}/{pr_number}/diff")
def get_pr_diff(owner: str, repo: str, pr_number: int):
    url = f"https://github.com/{owner}/{repo}/pull/{pr_number}.diff"
    response = requests.get(url, headers={"Accept": "application/vnd.github.v3.diff"})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return {"diff": response.text}

@app.get("/pull-request/{owner}/{repo}/{pr_number}/supported-diffs")
def get_supported_diffs(owner: str, repo: str, pr_number: int):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    response = requests.get(url, headers=auth_headers())
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    all_files = response.json()
    supported = [
        file for file in all_files
        if os.path.splitext(file['filename'])[1] in SUPPORTED_EXTENSIONS and 'patch' in file
    ]
    return {"supported_diffs": supported, "unsupported_count": len(all_files) - len(supported)}

@app.post("/pull-request/review")
def post_review(request: ReviewRequest):
    url = f"https://api.github.com/repos/{request.owner}/{request.repo}/pulls/{request.pr_number}/reviews"
    headers = auth_headers("application/vnd.github.v3+json")
    payload = {
        "body": request.review,
        "event": request.decision.upper(),
        "comments": []
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code >= 300:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()

@app.post("/pull-request/{owner}/{repo}/{pr_number}/request-reviewer")
def request_review(owner: str, repo: str, pr_number: int, reviewer: str = Query(...)):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"
    payload = {"reviewers": [reviewer]}
    response = requests.post(url, headers=auth_headers(), json=payload)
    if response.status_code != 201:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return {"message": "Reviewer requested"}
