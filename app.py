import os
import requests
import openai
import logging
from slack_bolt import App
from openai import OpenAI
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load tokens from environment variables for security
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
SLACK_APP_TOKEN = os.getenv('SLACK_APP_TOKEN')  # Needed for Socket Mode
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

# Initialize Slack app with Socket Mode
app = App(token=SLACK_BOT_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

# GitHub configuration
GITHUB_REPO = 'viratramesh03/TerraformTraining'  # Replace with your GitHub repository

# Updated GitHub search function
def search_github_docs(query):
    search_url = 'https://api.github.com/search/code'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    params = {
        'q': f'{query} repo:{GITHUB_REPO} extension:md',  # Ensure .md files are included
        'per_page': 5  # Limit results for efficiency
    }

    response = requests.get(search_url, headers=headers, params=params)

    if response.status_code == 200:
        logger.info(f"GitHub API Response: {response.json()}")
        results = response.json().get('items', [])
        if results:
            result_texts = []
            for item in results:
                file_path = item['path']
                html_url = item['html_url']
                result_texts.append(f"<{html_url}|{file_path}>")
            return "\n".join(result_texts)
        else:
            return "No relevant documentation found on GitHub."
    else:
        logger.error(f"GitHub API Error: {response.status_code} - {response.text}")
        return "Error searching GitHub documentation."

@app.event("message")
def handle_message_events(event, say):
    logger.info(f"Received event: {event}")  # Log the entire event

    # Ignore messages from bots
    if event.get('subtype') == 'bot_message':
        return

    user_query = event.get('text')
    logger.info(f"Received message: {user_query}")

    ai_message = "AI Response unavailable due to API limit."

    # Try generating response using OpenAI, but don't stop if it fails
    if user_query:
        try:
            # Use OpenAI to generate a response based on the user query
            ai_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": user_query}],
                max_tokens=150
            )
            ai_message = ai_response['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.error(f"Error with OpenAI: {e}")
            ai_message = "OpenAI response failed due to API limit or other errors."

    # Proceed to search GitHub for relevant Markdown files
    try:
        github_response = search_github_docs(user_query)
    except Exception as e:
        logger.error(f"Error with GitHub search: {e}")
        github_response = "Error searching GitHub documentation."

    # Send back the response to the Slack channel
    response_text = f"*AI Response:*\n{ai_message}\n\n*GitHub Documentation:*\n{github_response}"
    say(response_text)

# @app.event("app_mention")
# def handle_app_mention_events(event, say, logger):
#     # Ignore messages from bots
#     if event.get('subtype') == 'bot_message':
#         return

#     user_query = event.get('text')
#     logger.info(f"Received app_mention message: {user_query}")

#     if user_query:
#         try:
#             # Use OpenAI to generate a response based on the user query
#             ai_response = openai.completions.create(
#                 model="gpt-4o-mini",  # or any other model you want to use
#                 prompt=user_query,  # user input as the prompt
#                 max_tokens=150
#             )
#             ai_message = ai_response['choices'][0]['text'].strip()

#             # Search GitHub for relevant documentation
#             github_response = search_github_docs(user_query)

#             # Send back the response to the Slack channel
#             response_text = f"*AI Response:*\n{ai_message}\n\n*GitHub Documentation:*\n{github_response}"
#             say(response_text)
#         except Exception as e:
#             logger.error(f"Error processing app_mention: {e}")
#             say("Sorry, I encountered an error while processing your request.")

if __name__ == "__main__":
    # Ensure all required environment variables are set
    required_vars = ['SLACK_BOT_TOKEN', 'SLACK_APP_TOKEN', 'OPENAI_API_KEY', 'GITHUB_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        exit(1)

    handler = SocketModeHandler(app, os.getenv('SLACK_APP_TOKEN'))
    handler.start()
