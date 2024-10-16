import os
import git
import faiss
import numpy as np
import uvicorn
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI, HTTPException, Query, Form
from pydantic import BaseModel
from git.exc import GitCommandError
from typing import Dict, List
from collections import defaultdict

# Initialize the SentenceTransformer model for semantic search
model = SentenceTransformer('all-MiniLM-L6-v2')

# GitHub Personal Access Token for private repo access
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# GitHub API rate limit check
GITHUB_API_RATE_LIMIT = 5000
requests_made = 0

def check_rate_limit():
    global requests_made
    if requests_made >= GITHUB_API_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="GitHub API rate limit reached. Try again later.")
    requests_made += 1

# Function to clone or pull private GitHub repositories
def clone_or_pull_repo(repo_url, local_path):
    try:
        if repo_url.startswith("https://github.com/"):
            auth_repo_url = repo_url.replace("https://github.com/", f"https://{GITHUB_TOKEN}@github.com/")
        else:
            auth_repo_url = repo_url

        if not os.path.exists(local_path):
            print(f"Cloning repository {repo_url} to {local_path}")
            check_rate_limit()
            git.Repo.clone_from(auth_repo_url, local_path)
        else:
            print(f"Pulling latest changes from {repo_url}")
            repo = git.Repo(local_path)
            check_rate_limit()
            repo.remotes.origin.pull()

    except GitCommandError as e:
        raise HTTPException(status_code=500, detail=f"Error with Git command: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Function to fetch markdown files from repositories
def fetch_from_repos(repos: Dict[str, str]):
    docs = []
    for repo_url, local_path in repos.items():
        try:
            clone_or_pull_repo(repo_url, local_path)
            for root, dirs, files in os.walk(local_path):
                for file in files:
                    if file.endswith(".md"):
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, start=local_path)
                        docs.append((relative_path, file_path, repo_url))
        except HTTPException as e:
            print(f"Skipping repository {repo_url}: {e.detail}")
    return docs

# Function to vectorize documents
def vectorize_docs(docs):
    vectors = []
    for relative_path, file_path, repo_url in docs:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                vector = model.encode(content)
                vectors.append((relative_path, content, vector, repo_url))
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
    return vectors

# Store vectors in FAISS for similarity search
def store_in_faiss(vectors):
    dimension = 384
    index = faiss.IndexFlatL2(dimension)
    vector_data = np.array([v[2] for v in vectors], dtype='float32')
    index.add(vector_data)
    doc_mapping = {i: (v[0], v[1], v[3]) for i, v in enumerate(vectors)}  # (relative_path, content, repo_url)
    return index, doc_mapping

# Define repositories (add multiple actual URLs)
repos = {
    "https://github.com/ciec-infra/labweek.git": "test-vector-labweek",
    "https://github.com/ciec-infra/labweek-test.git": "test-vector-labweek-test"
}

# Fetch and vectorize documents
docs = fetch_from_repos(repos)
vectors = vectorize_docs(docs)
index, doc_mapping = store_in_faiss(vectors)

# Set up FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Welcome to the Vector API!"}

# Define the request body for search
class QueryRequest(BaseModel):
    query: str
    page: int = Query(1, gt=0)
    size: int = Query(3, gt=0)

# Cache for search results
cache = defaultdict(dict)

@app.post("/search/")
async def search_docs(query: QueryRequest):
    if query.query in cache and query.page in cache[query.query]:
        return cache[query.query][query.page]

    try:
        # Convert the query into a vector
        query_vector = model.encode(query.query).astype('float32')

        # Search the FAISS index for similar documents
        D, I = index.search(np.array([query_vector]), k=query.size * query.page)

        # Collect the matching document paths, snippets, and URLs
        results = []
        keyword_present_results = []

        for idx, i in enumerate(I[0]):
            if idx < query.size * query.page:
                if i in doc_mapping:
                    relative_path, content, repo_url = doc_mapping[i]
                    clean_repo_url = repo_url.replace(".git", "")
                    github_url = f"{clean_repo_url}/blob/main/{relative_path}"

                    # Check if the query keyword is present in the document
                    keyword_present = query.query.lower() in content.lower()

                    # Create a snippet around the keyword if it exists
                    snippet_start = max(content.lower().find(query.query.lower()) - 30, 0)
                    snippet_end = min(snippet_start + 60, len(content))
                    snippet = content[snippet_start:snippet_end].strip() + "..." if len(content) > 60 else content

                    # Store results with and without the keyword separately
                    result = {
                        "file_path": github_url,
                        "snippet": snippet,
                        "score": D[0][idx],
                        "content": content  # Return full content of the file
                    }

                    if keyword_present:
                        keyword_present_results.append(result)
                    else:
                        results.append(result)

        # Prioritize keyword-present results, then others
        sorted_results = keyword_present_results + results[:query.size - len(keyword_present_results)]

        # Cache the results
        if query.query not in cache:
            cache[query.query] = {}
        cache[query.query][query.page] = {"results": sorted_results}

        if len(sorted_results) == 0:
            return {"results": [], "message": "There is no document related to the search"}

        return {"results": sorted_results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during search: {str(e)}")

@app.post("/slack_command")
async def handle_slack_command(
    token: str = Form(...),
    team_id: str = Form(...),
    team_domain: str = Form(...),
    channel_id: str = Form(...),
    channel_name: str = Form(...),
    user_id: str = Form(...),
    user_name: str = Form(...),
    command: str = Form(...),
    text: str = Form(...),
    response_url: str = Form(...)
):
    try:
        # Prepare the query for your search endpoint
        query_request = {"query": text, "page": 1, "size": 3}

        # Send a request to your search endpoint
        response = await search_docs(QueryRequest(**query_request))

        # Respond back to Slack with URLs and content snippets
        if response["results"]:
            response_text = "\n".join([
                f"<{result['file_path']}|{result['file_path']}> (Score: {result['score']:.4f})\nSnippet: {result['snippet']}"
                for result in response["results"]
            ])
        else:
            response_text = "There is no document related to the search."

        return {
            "response_type": "in_channel",
            "text": response_text
        }

    except Exception as e:
        return {"text": f"Error during search: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
