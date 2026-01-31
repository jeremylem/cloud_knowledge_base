import boto3
from botocore.config import Config
import json
import os

# Increase read timeout for agent invocations (default 60s is too short)
bedrock = boto3.client(
    'bedrock-agent-runtime',
    config=Config(read_timeout=110)
)


def handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        query = body.get('query', '')

        if not query:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing query parameter'})
            }

        response = bedrock.invoke_agent(
            agentId=os.environ['AGENT_ID'],
            agentAliasId=os.environ['AGENT_ALIAS_ID'],
            sessionId=body.get('session_id', 'default'),
            inputText=query
        )

        # Collect response chunks
        answer = ""
        for event in response['completion']:
            if 'chunk' in event:
                chunk = event['chunk']
                if 'bytes' in chunk:
                    answer += chunk['bytes'].decode('utf-8')

        # Detect raw function markers (agent orchestration failure)
        if '<__function=' in answer or '<__parameter=' in answer:
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Agent orchestration failed. Try rephrasing your question.',
                    'query': query
                })
            }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'answer': answer,
                'query': query
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
