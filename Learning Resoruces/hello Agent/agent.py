from google.adk import Agent

root_agent = Agent(
    name="hello_agent",
    model="gemini-3.5-flash",
    instruction="You are a friendly assistant. Keep answers short.",
)
