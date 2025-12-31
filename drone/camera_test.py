from inference_sdk import InferenceHTTPClient

client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="7nth6oqWo8gBn3lEJBvR"
)

result = client.run_workflow(
    workspace_name="infoverseericsson",
    workflow_id="find-cats",
    images={
        "image": "A:\downloads\cat profile.jpg"
    },
    use_cache=True # cache workflow definition for 15 minutes
)

print(result)
