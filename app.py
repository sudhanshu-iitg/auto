from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS
import os
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from supabase import create_client, Client 
from libgen_api import LibgenSearch
from bs4 import BeautifulSoup
from requests.exceptions import ChunkedEncodingError, ConnectionError
import time
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError
import json
import io
import ebooklib
from ebooklib import epub
import google.generativeai as genai
import tempfile
# from main import send_tasks
# from file1 import send_tasks_1

NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('DATABASE_ID')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_USER_TOKEN = os.environ.get('SLACK_USER_TOKEN')
url: str = os.environ.get('SUPABASE_URL')
key: str = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(url, key)
my_api_key = os.environ.get('GEMINI_KEY')
client = WebClient(token=SLACK_TOKEN)
userId_dic = {}
channelId_dic = {}
notionId_dic={}
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
def download_epub(url, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            return response.content
        except (ChunkedEncodingError, ConnectionError) as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
            if attempt + 1 == max_retries:
                print("Max retries reached. Failed to download EPUB.")
            else:
                print("Retrying...")
    return None

def get_download_link(key, retries=5):
    for attempt in range(retries):
        try:
            page = requests.get(key)
            if page.status_code != 200:
                raise Exception(f"Failed to fetch the page. Status code: {page.status_code}")

            soup = BeautifulSoup(page.text, "html.parser")
            links = soup.find_all("a", string="GET")
            
            if not links:
                raise Exception("No links found with the specified string.")

            download_links = {link.string: link["href"] for link in links}
            
            if 'GET' in download_links:
                return 'http://libgen.li/' + download_links['GET']
            else:
                print("Download links are not available")
                return None

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                print("Retrying...")
                time.sleep(2)
            else:
                print("All retries failed. Exiting.")
                return None

def extract_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text()

def process_epub(epub_path, min_chapter_length=2200):
    book = epub.read_epub(epub_path)
    chapters = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            chapter_title = item.get_name()
            chapter_content = extract_text(item.get_content())
            
            if len(chapter_content) >= min_chapter_length:
                chapters.append((chapter_title, chapter_content))
            else:
                print(f"Skipping short content: {chapter_title} ({len(chapter_content)} characters)")

    return chapters

def call_gemini(contents, api_key):
    genai.configure(api_key=api_key)
    generation_config = {
        "temperature": 0,
        "max_output_tokens": 800,
        "response_mime_type": "text/plain"
    }
    model = genai.GenerativeModel(
        model_name="models/gemini-1.5-flash",
        generation_config=generation_config,
        system_instruction="You are a helpful assistant who executes given tasks accurately."
    )
    response = model.generate_content(contents)
    
    try:
        return response.text
    except:
        print(response)
        return None

def extract_chapter_info(json_string):
    try:
        data = json.loads(json_string)
        chapter_title = data['chapter_title']
        summary = data['summary']
        return chapter_title, summary
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error extracting chapter info: {e}")
        return None, None

def summarize_chapter(chapter_title, chapter_content):
    prompt = f'''Please summarize the chapter titled "{chapter_title}" in an engaging and concise manner. Focus on capturing the essence of the chapter, highlighting the most impactful moments, key concepts, and any notable developments. The goal is to create a summary that not only informs the reader but also draws them in, making the key takeaways clear and memorable.

After summarizing, suggest a compelling chapter title that encapsulates the main theme or focus of the chapter, aligning with the summary provided.

The chapter content is as follows:

{chapter_content[:4000]}  # Limit content to avoid exceeding token limits

Provide the output in the following JSON format:

  {{"chapter_title": "Suggested Chapter Title",
  "summary": "Summary of the chapter"}}
'''
    contents = [prompt]
    return call_gemini(contents, my_api_key)

def download_and_summarize(url, api_key,book_id):
    # Get the download link
    download_link = get_download_link(url)
    if not download_link:
        return "Failed to get download link"

    # Download the EPUB file
    epub_content = download_epub(download_link)
    if not epub_content:
        return "Failed to download EPUB"

    # Process the EPUB content
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.epub') as temp_file:
            temp_file.write(epub_content)
            temp_file_path = temp_file.name

        extracted_chapters = process_epub(temp_file_path)
    except Exception as e:
        return f"Failed to process EPUB: {str(e)}"
    finally:
        if 'temp_file_path' in locals():
            os.unlink(temp_file_path)

    # Summarize chapters
    summaries = {}
    for chapter_title, chapter_content in extracted_chapters:
        print(f"Summarizing chapter: {chapter_title}")
        summary = summarize_chapter(chapter_title, chapter_content)
        if summary:
            summary = summary.replace('```json\n', "").replace('\n```', "")
            new_chapter_title, new_summary = extract_chapter_info(summary)
            if new_chapter_title and new_summary:
                print(f"Summarizing complete: {new_chapter_title}")
                summaries[new_chapter_title] = new_summary
                chapter_id = get_or_create_chapter(book_id, new_chapter_title, chapter_content)
        time.sleep(2)  # To avoid hitting API rate limits
    summary_id = update_or_create_summary(book_id, summaries)
    return summaries

def get_or_create_category(category_name):
    # Check if category exists
    response = supabase.table("categories").select("id").eq("name", category_name).execute()
    if response.data:
        return response.data[0]['id']
    
    # If not, create new category
    insert_response = supabase.table("categories").insert({"name": category_name}).execute()
    return insert_response.data[0]['id'] if insert_response.data else None
def get_or_create_book(title, category_id,author):
    response = supabase.table("books").select("Id").eq("Title", title).eq("category_id", category_id).execute()
    if response.data:
        return response.data[0]['Id'], True  # Return True if book already exists
    
    insert_response = supabase.table("books").insert({"Title": title, "category_id": category_id,'Author':author}).execute()
    if insert_response.data:
        return insert_response.data[0]['Id'], False
    else:
        return None, False
def get_or_create_chapter(book_id, title, content):
    # Check if chapter exists
    response = supabase.table("chapter_contents").select("id").eq("book_id", book_id).eq("chapter_title", title).execute()
    if response.data:
        return response.data[0]['id']
    
    # If not, create new chapter
    insert_response = supabase.table("chapter_contents").insert({
        "book_id": book_id,
        "chapter_title": title,
        "content": content
    }).execute()
    return insert_response.data[0]['id'] if insert_response.data else None
def update_or_create_summary(book_id, summary):
    # Check if summary exists
    response = supabase.table("summaries").select("id").eq("book_id", book_id).execute()
    if response.data:
        # Update existing summary
        update_response = supabase.table("summaries").update({"content": summary}).eq("id", response.data[0]['id']).execute()
        return update_response.data[0]['id'] if update_response.data else None
    
    # If not, create new summary
    insert_response = supabase.table("summaries").insert({
        "book_id": book_id,
        "content": summary
    }).execute()
    return insert_response.data[0]['id'] if insert_response.data else None

def get_tasks_and_user_ids():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    response = requests.post(url, json={"page_size": 100}, headers=headers)
    if response.status_code == 200:
        data = response.json()
        tasks_and_user_ids = [
            (
                task["properties"]["Task"]["title"][0]["text"]["content"],
                task["properties"]['Task owner']['people'][0]['name'],
                task["id"],
                task["properties"]['Status']['select']['name']
            )
            for task in data["results"]
        ]
        return tasks_and_user_ids
    else:
        # logger.error(f"Error fetching data from Notion API: {response.text}")
        return []
    
def send_task(task, user_id, notion_page_id,user_name):
    result = client.chat_postMessage(channel=user_id, text=f"Good evening, {user_name}! Could you please provide an update on the progress of {task} today? Thank you!")
    userId_dic[task] = result["message"]["ts"]
    channelId_dic[user_id] = result["channel"]
    notionId_dic[result["message"]["ts"]] = notion_page_id

def get_id_from_name(user_name):
    url = f"https://slack.com/api/users.list"
    response = requests.get(
        url,
        headers={"Authorization":f"Bearer {SLACK_USER_TOKEN}"}
    )
    if response.json()['members'] is not None:
        member_list = []
        for member in response.json()['members']:
            member_list.append(member['name'])
            if user_name.lower().strip() in member['name'].lower().strip() :
                return member['id']
        send_task(f"Couldn't find the user -  {member_list}", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
    else:
        return "U03GP4QD0MU"


def send_tasks():
    try:
        tasks_and_user_ids = get_tasks_and_user_ids()
        for task, user_name, notion_page_id, status in tasks_and_user_ids:
            if status == 'in progress':
                user_id = get_id_from_name(user_name)
                if user_name is None:
                    send_task("really fucked up", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
                else:
                    if user_id is None:
                        send_task(f"Couldn't find the user -  {user_name}", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
                    else:
                        send_task(task, user_id, notion_page_id,user_name)     
    except Exception as e:
        print(f"An error occurred: {e}")

def update_notion_reply(reply, notion_page_id):
    url = f"https://api.notion.com/v1/comments"
    response = requests.post(
        url,
        json={"parent": {"page_id": notion_page_id },"rich_text": [
        {"text": {"content": reply}}]},headers=headers
    )

def download_pdf(url, save_path, max_retries=3):
    # Attempt to download with retries
    for attempt in range(max_retries):
        try:
            # Send GET request with stream=True to download in chunks
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Open the file in write-binary mode
            with open(save_path, 'wb') as file:
                # Write the content in chunks to avoid large memory usage
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        file.write(chunk)
            print(f"PDF downloaded successfully and saved to {save_path}")
            break  # Exit the loop if the download was successful
        except (ChunkedEncodingError, ConnectionError) as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
            if attempt + 1 == max_retries:
                print("Max retries reached. Failed to download PDF.")
            else:
                print("Retrying...")   

app = Flask(__name__)
CORS(app, resources={r"/search*": {"origins": ["http://localhost:3000", "https://the-book-app2.onrender.com"]}})
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        # Process the data here
        if data.get("challenge") is not None:
            challenge = data.get("challenge")
            return challenge, 200
        else:
            # Handle other webhook events here
            print(f"Received webhook data: {data}")
            send_tasks()
            return jsonify({"message": "Webhook received!", "data": data}), 200

@app.route('/slack', methods=['POST'])
def slack():
    if request.method == 'POST':
        data1 = request.json
        # send_task(f"Received webhook data: {data1} ", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d")
        # Process the data here
        if data1.get("challenge") is not None:
            # send_tasks_1()
            challenge = data1.get("challenge")
            return challenge, 200
        else:
            # Handle other webhook events here
            data, count = supabase.table('Request logs').insert({ "Request": data1["event"]}).execute()
            if "thread_ts" in data1["event"]:
                id = notionId_dic.get(data1["event"]["thread_ts"], 'test')
                update_notion_reply(data1["event"]["text"],id)
            # response = requests.post("https://smee.io/xK7FU4adUFN3EO8", data={"body":str(data1),"id":id })
            
            return jsonify({"message": "Webhook received !", "data": data1}), 200

@app.route('/search', methods=['GET'])
def search():
    if request.method == 'GET':
        key = request.args.get("key")
        if key is not None:
            # send_tasks_1()
            s = LibgenSearch()
            results = s.search_title(key)
            count = 0
            new_results = []
            for result in results:
                if result['Extension'] == 'epub':
                    result["download_links"] = result['Mirror_2']
                    new_results.append(result)
                    count += 1
                    if count >= 10:
                        break
            return jsonify({"message": "returned successfully!", "docs": new_results}), 200
            # return challenge, 200
        else:
            return jsonify({"message": "Missing 'key' parameter"}), 400 
@app.route('/store', methods=['GET'])
def store():
    if request.method == 'GET':
        try:
            key = request.args.get("key")
            if key is None:
                return jsonify({"error": "Missing 'key' parameter"}), 400

            url = request.args.get("url")
            if url is None:
                return jsonify({"error": "Missing 'url' parameter"}), 400

            book_title = request.args.get("title")
            if book_title is None:
                return jsonify({"error": "Missing 'title' parameter"}), 400

            author = request.args.get("author")
            if author is None:
                return jsonify({"error": "Missing 'author' parameter"}), 400

            my_api_key = os.environ.get('GEMINI_KEY')
            if my_api_key is None:
                return jsonify({"error": "GEMINI_KEY environment variable is not set"}), 500

            book_category = 'New'
            category_id = get_or_create_category(book_category)
            if category_id is None:
                return jsonify({"error": "Failed to create or get category"}), 500

            book_id, book_exists = get_or_create_book(book_title, category_id, author)
            if book_id is None:
                return jsonify({"error": "Failed to create or get book"}), 500

            if book_exists:
                return jsonify({"message": "Book already exists", "book_id": book_id}), 200

            result = download_and_summarize(url, my_api_key, book_id)
            if result is None:
                return jsonify({"error": "Failed to download and summarize the book"}), 500

            return jsonify({"message": "Book processed successfully", "book_id": book_id, "summary": result}), 200

        except Exception as e:
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

    return jsonify({"error": "Method not allowed"}), 405

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port,debug=False)

# Schedule the send_tasks function to run at 11:10 every day
# schedule.every().day.at("23:30").do(send_tasks)

# # Run the scheduled tasks
# while True:
#     schedule.run_pending()
#     time.sleep(6000)

