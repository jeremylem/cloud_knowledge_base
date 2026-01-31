# Notes Assistant with Bedrock AgentCore

A RAG chatbot for personal notes using S3 Vectors and Bedrock AgentCore. Features self-critique evaluation loop and multi-turn conversations. Built as a learning exercise after re:Invent 2025.

## Why I Built This

I already have [virtualme](https://github.com/ox00004a/virtualme) running in production. It's a RAG chatbot using DynamoDB for vector storage. It works, stays in free tier, does the job.

But re:Invent 2025 announced two things that caught my attention:

- **Amazon S3 Vectors** (December 2025). Native vector storage with similarity search. No more client-side cosine calculations.
- **Amazon Bedrock AgentCore** (December 2025). Managed agent infrastructure with built-in tool orchestration.

I wanted to understand how these compare to my DynamoDB approach. What do I gain? What do I lose?

This project is that exploration.

---

## Architecture

```
                        DEPLOYMENT
                        ==========

./deploy.sh
     |
     v
+------------------+
|  S3 Bucket       |  <-- your .md/.txt notes go here
|  (notes/)        |
+--------+---------+
         |
         v
+------------------+
|  Bedrock         |  reads notes, chunks them
|  Knowledge Base  |  calls Titan Embeddings (1024 dims)
+--------+---------+
         |
         v
+------------------+
|  S3 Vectors      |  <-- vectors stored here
|  Index           |      native similarity search
+------------------+
```

```
                         QUERY FLOW
                         ==========

python client.py "What is DynamoDB?"
     |
     | HTTPS + SigV4 signing
     v
+------------------+     +------------------+
|  Lambda          | --> |  Bedrock Agent   |
|  Function URL    |     |  (Nova Lite v1)  |
+------------------+     +--------+---------+
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
           +----------------+          +----------------+
           |  Knowledge     |          |  Evaluator     |
           |  Base Search   |          |  Lambda        |
           +----------------+          +----------------+
                                              |
                                              v
                                       score < 7?
                                       revise (max 3x)
                                              |
                                              v
                                        Final Answer
```

---

## What I Wanted to Learn

### 1. AWS SAM

I've used Terraform and CDK before. Never SAM.

SAM handles Lambda packaging automatically. You point it at a directory, it zips and uploads:

```yaml
EvaluatorLambda:
  Type: AWS::Serverless::Function
  Properties:
    Runtime: python3.13
    Handler: evaluator.handler
    CodeUri: ../lambda/    # SAM packages this
```

Run `sam build`, it creates `.aws-sam/build/` with deployment artifacts. Run `sam deploy --resolve-s3`, it handles the S3 bucket for you.

Good: Less config than raw CloudFormation.
Bad: Another abstraction layer to debug when things break.

### 2. S3 Vectors vs DynamoDB

**virtualme approach:**
```python
# Client-side similarity calculation
for item in dynamodb.scan():
    score = cosine_similarity(query_vector, item['embedding'])
```

**S3 Vectors approach:**
```yaml
VectorIndex:
  Type: AWS::S3Vectors::Index
  Properties:
    Dimension: 1024
    DistanceMetric: cosine   # server-side!
```

No Python similarity code. Bedrock handles the vector search natively.

Trade-off: S3 Vectors has a 2048-byte limit on filterable metadata per record. I'll get to that.

### 3. Bedrock AgentCore

Instead of manually chaining retrieval + generation + evaluation in Python, the agent handles it:

```yaml
NotesAgent:
  Type: AWS::Bedrock::Agent
  Properties:
    FoundationModel: amazon.nova-lite-v1:0
    KnowledgeBases:
      - KnowledgeBaseId: !Ref KnowledgeBase
    ActionGroups:
      - ActionGroupName: ResponseEvaluation
        ActionGroupExecutor:
          Lambda: !GetAtt EvaluatorLambda.Arn
```

The agent decides when to search, when to evaluate, when to revise. I just write the instructions.

The bigger feature is multi-agent interactions. AgentCore makes it straightforward to have agents collaborate or delegate tasks to each other. For this project, the self-critique loop was mostly an excuse to play with that capability. It potentially costs more (each evaluation is another model call) and the real benefits need to be evaluated for each use case.

---

## Things That Broke

### The 2048-byte Metadata Limit

First deployment. Ingestion job fails with `Filterable metadata must have at most 2048 bytes`.

Bedrock stores chunk text in filterable metadata by default. Even small paragraphs exceed 2048 bytes. I tried shorter filenames, smaller chunks, different chunking strategies. Nothing worked because the limit is per-record, not total.

The fix is to configure the index to treat Bedrock metadata as non-filterable:

```yaml
VectorIndex:
  Type: AWS::S3Vectors::Index
  Properties:
    MetadataConfiguration:
      NonFilterableMetadataKeys:
        - AMAZON_BEDROCK_TEXT
        - AMAZON_BEDROCK_METADATA
```

Catch: This must be set at index creation. I had to destroy the stack and redeploy.

### Nova Lite 2 and the PRE_PROCESSING Trap

I asked about DynamoDB. My notes contain detailed information about DynamoDB. The agent returned `<__function=outOfDomain>` without even searching.

Nova Lite 2 has an aggressive PRE_PROCESSING step that classifies queries before searching. It was deciding "this isn't my job" and refusing to look at the knowledge base. Claude Haiku worked fine with the same setup.

I overrode the PRE_PROCESSING step to skip domain classification:

```yaml
PromptOverrideConfiguration:
  PromptConfigurations:
    - PromptType: PRE_PROCESSING
      PromptState: DISABLED
      PromptCreationMode: OVERRIDDEN
      BasePromptTemplate: |
        {
          "system": "Classify all inputs as Category D (can be answered by the agent).",
          "messages": [{"role": "user", "content": [{"text": "Input: $question$"}]}]
        }
```

When overriding prompts, you must use `PromptCreationMode: OVERRIDDEN` with a custom `BasePromptTemplate`. Can't mix and match. CloudFormation will reject it otherwise.

### Nova Lite 2 Orchestration Issues

Even after fixing PRE_PROCESSING, Nova Lite 2 had more issues. Some queries returned raw function markers instead of executing them:

```
<__function=GET__x_amz_knowledgebase_XXXXX__Search>
<__parameter=searchQuery>S3</__parameter>
</__function>
```

The behavior was inconsistent. "What is S3?" showed raw markers. "Explain S3 storage classes" worked fine. "What is SOLID?" hit content filters or timed out.

I switched to **Nova Lite v1** (`amazon.nova-lite-v1:0`). Same price tier, stable orchestration. All queries work consistently. Nova Lite 2 might have a bug with Bedrock Agent orchestration, or maybe I'm missing something in my configuration. Either way, the older version works.

---

## Cold Start Reality

First query after deployment or idle:

| Component | Time |
|-----------|------|
| API Lambda init | ~500ms |
| Evaluator Lambda init | ~500ms per evaluation |
| Bedrock Agent session | variable |
| Knowledge Base connection | first query slower |

**First query:** 15-30 seconds (everything cold)
**Warm queries:** 3-8 seconds
**After 15 min idle:** Agent session expires, partial cold start

virtualme has the same cold start issues. Serverless trade-off.

---

## Cost Comparison

### This Project (S3 Vectors + AgentCore)

| Component | Monthly Cost |
|-----------|-------------|
| S3 Vectors storage | < $0.01 |
| S3 Vectors queries | < $0.01 |
| Titan Embeddings (ingestion) | < $0.01 |
| Nova Lite v1 (queries) | ~$0.05-0.10 |
| Lambda | free tier |
| **Total** | **~$0.10-0.15** |

### virtualme (DynamoDB)

| Component | Monthly Cost |
|-----------|-------------|
| DynamoDB | free tier |
| Bedrock model | ~$0.05-0.10 |
| Lambda | free tier |
| **Total** | **~$0.05-0.10** |

### Session Storage

Bedrock Agent sessions are configured with `IdleSessionTTLInSeconds: 600` (10 minutes). After 10 minutes of inactivity, the session expires and conversation context is lost.

Session storage itself is free. Idle time doesn't cost anything. What costs tokens is conversation history. The agent includes previous turns in each request:

```
Turn 1: "What is S3?"           →  ~50 input tokens
Turn 2: "Tell me more"          → ~150 input tokens (includes Turn 1)
Turn 3: "How about pricing?"    → ~300 input tokens (includes Turn 1+2)
```

For light usage (~100 queries/month), the difference is negligible.

### Verdict

DynamoDB is cheaper because I hacked it. In virtualme, I scan all items and calculate cosine similarity client-side. This works because my notes corpus produces fewer than 1000 chunks. Beyond that, it would get slow and expensive.

S3 Vectors costs slightly more but removes all that custom code. Native similarity search, no client-side calculations, no manual orchestration. For anything larger than a small personal project, managed infrastructure wins.

---

## Prerequisites

- AWS CLI configured
- SAM CLI installed
- `jq` (`brew install jq`)
- Bedrock model access in eu-west-3 (Nova Lite v1, Titan Embeddings)
- Python 3 with `boto3` and `requests`

## Usage

```bash
# configure
cp config.json.example config.json
# edit with your bucket name and notes directory

# deploy
./deploy.sh

# query
python3 client.py "What is DynamoDB?"

# teardown
./destroy.sh
```

---

## What I Learned

1. **S3 Vectors has edge cases.** The 2048-byte metadata limit is not documented prominently. Cost me a few hours.

2. **Different LLMs behave differently.** Nova and Claude interpret the same agent prompts differently. Test with your actual model.

3. **Nova Lite 2 had issues with agent orchestration.** It sometimes output function calls as text instead of executing them. Could be a bug, could be my configuration. Nova Lite v1 (older version) works fine. Not all model versions behave the same for agent orchestration.

4. **SAM is convenient but adds abstraction.** When it works, great. When it breaks, you're debugging two layers.

5. **AgentCore simplifies orchestration.** No manual chaining of retrieval + generation. But you lose visibility into the middle steps.

6. **Multi-agent is the real value.** AgentCore makes agent collaboration easy to set up. Whether it's worth the extra cost depends on your use case.

7. **Free tier is hard to beat (in my case).** DynamoDB + custom code is cheaper only because I have fewer than 1000 chunks. I scan everything and compute similarity client-side. This hack won't scale. For anything larger, managed services like S3 Vectors are the right choice.

---

## Resources

- [S3 Vectors announcement](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-s3-vectors-preview/)
- [Bedrock AgentCore docs](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [virtualme (the DynamoDB approach)](https://github.com/ox00004a/virtualme)
