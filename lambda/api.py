import boto3
import json
import os

lambda_client = boto3.client('lambda')

ORCHESTRATOR_FUNCTION_NAME = os.environ.get('ORCHESTRATOR_FUNCTION_NAME')


def handler(event, context):
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        query = body.get('query')
        session_id = body.get('session_id')

        if not query:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Missing query parameter'})
            }

        print(f"Invoking orchestrator for query: {query}")

        # Build orchestrator payload
        orchestrator_payload = {'query': query}
        if session_id:
            orchestrator_payload['session_id'] = session_id

        # Invoke orchestrator Lambda
        response = lambda_client.invoke(
            FunctionName=ORCHESTRATOR_FUNCTION_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps(orchestrator_payload)
        )

        # Parse orchestrator response
        result = json.loads(response['Payload'].read().decode('utf-8'))

        # Check for errors
        if 'error' in result:
            return {
                'statusCode': result.get('statusCode', 500),
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': result['error']})
            }

        # Return successful response
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'answer': result.get('response', ''),
                'query': query,
                'metadata': {
                    'iterations': result.get('iterations', 1),
                    'score': result.get('final_score', 0),
                    'session_id': result.get('session_id', ''),
                    'max_iterations_reached': result.get('max_iterations_reached', False)
                }
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }
