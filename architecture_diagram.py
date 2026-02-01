from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.storage import S3
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import IAM
from diagrams.aws.general import User

graph_attr = {
    "bgcolor": "white",
    "pad": "0.5",
    "splines": "spline",
}

with Diagram(
    "Multi-Agent RAG Architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    outformat="png",
):
    user = User("Python Client\n(SigV4 signing)")

    with Cluster("API Layer"):
        iam = IAM("IAM Auth")
        api_lambda = Lambda("API Lambda\n(Function URL)")

    with Cluster("Orchestration"):
        orchestrator = Lambda("Orchestrator")

    with Cluster("Bedrock Agents"):
        research = Bedrock("Research")
        critique = Bedrock("Critique")
        formatter = Bedrock("Formatter")

    with Cluster("Knowledge Base"):
        kb = Bedrock("KB + Titan\nEmbeddings")

    with Cluster("Storage"):
        s3_notes = S3("S3 Bucket\n(notes/)")
        s3_vectors = S3("S3 Vectors\n(embeddings)")

    # User to API
    user >> Edge(label="HTTPS POST") >> iam >> api_lambda

    # API to Orchestrator
    api_lambda >> Edge(label="invoke") >> orchestrator

    # Orchestrator to Agents
    orchestrator >> Edge(label="1. query") >> research
    research >> Edge(label="2. evaluate") >> critique
    critique >> Edge(label="3. feedback", style="dashed", color="orange") >> research
    critique >> Edge(label="4. approved") >> formatter
    formatter >> Edge(label="5. response") >> orchestrator

    # Research uses Knowledge Base
    research >> Edge(label="RAG") >> kb

    # Knowledge Base connections
    s3_notes >> Edge(label="ingest") >> kb
    kb >> Edge(label="index") >> s3_vectors
