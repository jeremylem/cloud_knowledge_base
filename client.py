#!/usr/bin/env python3
import boto3
import json
import readline  # enables line editing (backspace, arrows, history)
import sys
import uuid
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests

STACK_NAME = "notes-assistant"
REGION = "eu-west-3"


def get_api_url():
    """Retrieve API endpoint from CloudFormation stack outputs."""
    cf = boto3.client('cloudformation', region_name=REGION)
    outputs = cf.describe_stacks(StackName=STACK_NAME)['Stacks'][0]['Outputs']
    return next(o['OutputValue'] for o in outputs if o['OutputKey'] == 'ApiEndpoint')


def sign_request(url, payload):
    """Sign request with SigV4 using AWS credentials."""
    session = boto3.Session()
    credentials = session.get_credentials()

    request = AWSRequest(
        method="POST",
        url=url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"}
    )

    SigV4Auth(credentials, "lambda", REGION).add_auth(request)
    return dict(request.headers)


class NotesAssistant:
    def __init__(self):
        self.api_url = get_api_url()
        self.session_id = str(uuid.uuid4())

    def query(self, question, verbose=False):
        payload = {"query": question, "session_id": self.session_id}
        headers = sign_request(self.api_url, payload)

        response = requests.post(self.api_url, json=payload, headers=headers, timeout=300)

        if response.status_code == 403:
            return {"answer": "Error: Access denied. Check your AWS credentials."}

        data = response.json()

        if "error" in data:
            return {"answer": f"Error: {data['error']}"}

        result = {"answer": data.get("answer", "No answer received")}
        if "metadata" in data:
            result["metadata"] = data["metadata"]

        return result

    def new_session(self):
        self.session_id = str(uuid.uuid4())


def interactive_mode():
    """Run interactive chat session."""
    print("Notes Assistant (type /help for commands, /quit to exit)")
    print("-" * 50)

    assistant = NotesAssistant()
    verbose = False
    print(f"Session: {assistant.session_id[:8]}...")
    print()

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue

        if question == "/quit":
            print("Bye!")
            break
        elif question == "/new":
            assistant.new_session()
            print(f"New session: {assistant.session_id[:8]}...")
        elif question == "/verbose":
            verbose = not verbose
            print(f"Verbose mode: {'on' if verbose else 'off'}")
        elif question == "/help":
            print("Commands:")
            print("  /new     - Start new conversation session")
            print("  /verbose - Toggle metadata display")
            print("  /quit    - Exit")
            print("  /help    - Show this help")
        else:
            print()
            result = assistant.query(question)
            print(result["answer"])
            if verbose and "metadata" in result:
                meta = result["metadata"]
                print()
                print(f"[iterations: {meta.get('iterations', '?')}, score: {meta.get('score', '?')}/10]")
            print()


def single_query(question, verbose=False):
    """Run single query and exit."""
    assistant = NotesAssistant()
    result = assistant.query(question)
    print(result["answer"])
    if verbose and "metadata" in result:
        meta = result["metadata"]
        print()
        print(f"[iterations: {meta.get('iterations', '?')}, score: {meta.get('score', '?')}/10]")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        interactive_mode()
    elif len(sys.argv) == 2:
        if sys.argv[1] == "-v":
            interactive_mode()
        else:
            single_query(sys.argv[1])
    elif len(sys.argv) == 3 and sys.argv[1] == "-v":
        single_query(sys.argv[2], verbose=True)
    else:
        print("Usage:")
        print("  python client.py                     # Interactive mode")
        print("  python client.py 'Your question'     # Single query")
        print("  python client.py -v 'Your question'  # Single query with metadata")
        sys.exit(1)
