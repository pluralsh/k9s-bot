import os
import json
import httpx

PLURAL_CONSOLE_URL = os.getenv("PLURAL_CONSOLE_URL", "https://console.plrldemo.onplural.sh")
PLURAL_GQL_ENDPOINT = f"{PLURAL_CONSOLE_URL}/gql"
PAT = os.getenv("PLURAL_PAT")

CREATE_AGENT_SESSION_MUTATION = """mutation CreateAgentSession($attributes: AgentSessionAttributes!) {
  createAgentSession(attributes: $attributes) {
    id 
  }
}
"""


class AskPlural:
    """Tool for sending prompts to the Plural AI agent to manage infrastructure."""
    
    def __init__(self):
        self.name = "ask_plural"
        self.description = "Ask Plural AI to make infrastructure changes, like scaling databases, modifying deployments, or managing Kubernetes resources. Use this when the user wants to make changes to their cloud infrastructure."
        self.file = "tools/plural.json"
    
    async def act(self, params):
        if isinstance(params, str):
            params = json.loads(params)
        
        prompt = params.get("prompt", "")
        if not prompt:
            return "Error: No prompt provided for Plural agent"
        
        if not PAT:
            return "Error: PLURAL_PAT environment variable is not set. Please set your Plural Personal Access Token."
        
        headers = {
            "accept": "*/*",
            "authorization": f"Token {PAT}",
            "content-type": "application/json",
        }
        
        payload = {
            "operationName": "CreateAgentSession",
            "variables": {
                "attributes": {
                    "type": "TERRAFORM",
                    "prompt": prompt
                }
            },
            "query": CREATE_AGENT_SESSION_MUTATION
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PLURAL_GQL_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                if "errors" in result:
                    error_messages = [e.get("message", "Unknown error") for e in result["errors"]]
                    return f"Plural API returned errors: {', '.join(error_messages)}"
                
                data = result.get("data", {})
                session = data.get("createAgentSession", {})
                
                if session:
                    session_id = session.get("id", "unknown")
                    return f"Successfully created Plural agent session (ID: {session_id}). The agent is now processing your request: '{prompt}'"
                else:
                    return f"Request sent to Plural successfully, but no session data returned. Response: {json.dumps(result)}"
                    
        except httpx.HTTPStatusError as e:
            return f"Error calling Plural API: HTTP {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return f"Error connecting to Plural API: {str(e)}"
        except Exception as e:
            return f"Unexpected error calling Plural API: {str(e)}"
    
    def tool(self, Tool):
        return Tool(
            name=self.name,
            description=self.description,
            filepath=self.file,
            callback=self.act,
            awake=True,
        )

