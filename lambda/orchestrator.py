import boto3
import json
import re
import os
import uuid

bedrock = boto3.client('bedrock-agent-runtime')

RESEARCH_AGENT_ID = os.environ.get('RESEARCH_AGENT_ID')
RESEARCH_AGENT_ALIAS_ID = os.environ.get('RESEARCH_AGENT_ALIAS_ID')
CRITIQUE_AGENT_ID = os.environ.get('CRITIQUE_AGENT_ID')
CRITIQUE_AGENT_ALIAS_ID = os.environ.get('CRITIQUE_AGENT_ALIAS_ID')
FORMATTER_AGENT_ID = os.environ.get('FORMATTER_AGENT_ID')
FORMATTER_AGENT_ALIAS_ID = os.environ.get('FORMATTER_AGENT_ALIAS_ID')
MAX_ITERATIONS = int(os.environ.get('MAX_ITERATIONS', '3'))
MIN_SCORE = int(os.environ.get('MIN_SCORE', '7'))


def invoke_agent(agent_id, agent_alias_id, input_text, session_id):
    """Invoke a Bedrock agent and extract the response text."""
    response = bedrock.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=input_text
    )

    # Process streaming response
    completion = ""
    for event in response.get('completion', []):
        if 'chunk' in event:
            chunk = event['chunk']
            if 'bytes' in chunk:
                completion += chunk['bytes'].decode('utf-8')

    return completion


def extract_score(critique_text):
    """Parse 'Score: X/10' from critique response."""
    match = re.search(r'Score:\s*(\d+)', critique_text)
    return int(match.group(1)) if match else 5


def extract_feedback(critique_text):
    """Parse 'Feedback: [details]' from critique response."""
    match = re.search(r'Feedback:\s*(.+)', critique_text, re.DOTALL)
    return match.group(1).strip() if match else "Please provide more detail and citations"


def handler(event, context):
    """Orchestrate multi-agent workflow with critique loop."""
    query = event.get('query', '')
    session_id = event.get('session_id', str(uuid.uuid4()))

    if not query:
        return {
            'statusCode': 400,
            'error': 'Missing query parameter'
        }

    print(f"Starting orchestration for query: {query}")
    print(f"Session ID: {session_id}")

    feedback = None
    research = None
    score = 0

    for iteration in range(MAX_ITERATIONS):
        print(f"--- Iteration {iteration + 1}/{MAX_ITERATIONS} ---")

        # Step 1: Research Agent
        if iteration == 0:
            research_prompt = query
        else:
            research_prompt = f"{query}\n\nPlease improve your research based on this feedback: {feedback}"

        print(f"Invoking Research Agent...")
        research = invoke_agent(
            RESEARCH_AGENT_ID,
            RESEARCH_AGENT_ALIAS_ID,
            research_prompt,
            session_id
        )
        print(f"Research response length: {len(research)}")

        # Step 2: Critique Agent
        critique_prompt = f"Evaluate this research for the query '{query}':\n\n{research}"
        print(f"Invoking Critique Agent...")
        critique = invoke_agent(
            CRITIQUE_AGENT_ID,
            CRITIQUE_AGENT_ALIAS_ID,
            critique_prompt,
            session_id
        )
        print(f"Critique: {critique[:200]}...")

        # Extract score and feedback
        score = extract_score(critique)
        feedback = extract_feedback(critique)
        print(f"Score: {score}/10")

        # Step 3: Check if good enough
        if score >= MIN_SCORE:
            print(f"Score {score} >= {MIN_SCORE}, proceeding to formatter")
            break

        print(f"Score {score} < {MIN_SCORE}, will retry with feedback")

    # Step 4: Format final response
    format_prompt = f"Create a helpful answer for this question: {query}\n\nUsing this research:\n{research}"
    print(f"Invoking Formatter Agent...")
    response = invoke_agent(
        FORMATTER_AGENT_ID,
        FORMATTER_AGENT_ALIAS_ID,
        format_prompt,
        session_id
    )

    result = {
        'response': response,
        'session_id': session_id,
        'iterations': iteration + 1,
        'final_score': score
    }

    if iteration + 1 == MAX_ITERATIONS and score < MIN_SCORE:
        result['max_iterations_reached'] = True

    print(f"Orchestration complete: {iteration + 1} iterations, score {score}")
    return result
