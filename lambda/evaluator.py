import boto3
import json
import os
import re

bedrock = boto3.client('bedrock-runtime')
MODEL_ID = os.environ.get('MODEL_ID', 'eu.amazon.nova-lite-v1:0')

EVALUATOR_PROMPT = """You are an evaluator assessing the quality of a response to a user query.

Original Query: {query}

Draft Response: {response}

Evaluate the response on these criteria:
1. Relevance: Does it address the query?
2. Accuracy: Is the information correct based on the context?
3. Completeness: Does it fully answer the question?
4. Clarity: Is it well-structured and easy to understand?

Provide a score from 1-10 (7+ is acceptable) and brief feedback.
Respond ONLY with valid JSON in this exact format:
{{"score": 8, "feedback": "Your feedback here"}}"""


def extract_json(text):
    match = re.search(r'\{[^{}]*"score"[^{}]*\}', text)
    if match:
        return json.loads(match.group())
    return None


def evaluate(query, draft):
    prompt = EVALUATOR_PROMPT.format(query=query, response=draft)
    result = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': 500, 'temperature': 0.1}
    )
    output_text = result['output']['message']['content'][0]['text']
    evaluation = extract_json(output_text)
    if not evaluation:
        evaluation = {'score': 5, 'feedback': output_text[:200]}
    return evaluation


def handler(event, context):
    try:
        # Check if this is a Bedrock Agent invocation
        if 'actionGroup' in event:
            # Extract parameters from Bedrock Agent format
            params = {p['name']: p['value'] for p in event.get('parameters', [])}
            query = params.get('original_query', '')
            draft = params.get('draft_response', '')

            evaluation = evaluate(query, draft)

            # Return Bedrock Agent format
            return {
                'messageVersion': '1.0',
                'response': {
                    'actionGroup': event['actionGroup'],
                    'function': event.get('function', 'evaluate_response'),
                    'functionResponse': {
                        'responseBody': {
                            'TEXT': {'body': json.dumps(evaluation)}
                        }
                    }
                }
            }
        else:
            # Direct invocation (for testing)
            body = event if isinstance(event, dict) else json.loads(event.get('body', '{}'))
            query = body.get('original_query', '')
            draft = body.get('draft_response', '')

            evaluation = evaluate(query, draft)

            return {
                'statusCode': 200,
                'body': json.dumps(evaluation)
            }

    except Exception as e:
        if 'actionGroup' in event:
            return {
                'messageVersion': '1.0',
                'response': {
                    'actionGroup': event.get('actionGroup', ''),
                    'function': event.get('function', ''),
                    'functionResponse': {
                        'responseState': 'FAILURE',
                        'responseBody': {
                            'TEXT': {'body': json.dumps({'error': str(e)})}
                        }
                    }
                }
            }
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
