from openai import OpenAI
from dotenv import load_dotenv
import os
load_dotenv()

FACTCHAT_API_KEY = os.environ.get("FACTCHAT_API_KEY")

client = OpenAI(
    api_key=FACTCHAT_API_KEY,
    base_url="https://factchat-cloud.mindlogic.ai/v1/gateway",
)

models = client.models.list()
for model in models.data:
    print(model.id)