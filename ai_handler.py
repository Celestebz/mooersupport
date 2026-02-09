import json
import re
import logging
import os
from dotenv import load_dotenv
from openai import OpenAI

class AIHandler:
    """
    Handles interactions with Generative AI models via OpenAI-compatible API.
    """
    
    def __init__(self):
        """Initialize AI Handler"""
        self.logger = logging.getLogger(__name__)
        load_dotenv()
        
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.enabled = os.getenv("LLM_ENABLED", "False").lower() == "true"
        
        self.client = None
        if self.enabled and self.api_key:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
                self.logger.info(f"AI Handler initialized with model: {self.model}")
            except Exception as e:
                self.logger.error(f"Failed to initialize OpenAI client: {e}")
                self.enabled = False
        else:
            if not self.enabled:
                self.logger.info("AI Handler is disabled via configuration")
            elif not self.api_key:
                self.logger.warning("AI Handler enabled but LLM_API_KEY is missing")
                self.enabled = False

    def analyze_email_content(self, email_subject, email_body):
        """
        Analyze email content to extract structured information using AI.
        
        Returns:
            dict: {
                "product_model": str,
                "intent": str,
                "urgency": str,
                "sentiment": str,
                "key_issues": list,
                "language": str
            }
        """
        if not self.enabled or not self.client:
            return {
                "product_model": "Unknown",
                "intent": "Technical Support",
                "urgency": "Medium",
                "sentiment": "Neutral",
                "key_issues": ["AI Unavailable"],
                "language": "en"
            }
            
        try:
            clean_body = email_body[:3000] # Increased context window
            
            prompt = f"""
You are an expert content analyzer for Mooer Audio customer support.
Analyze the following email and extract structured data.

EMAIL INFO:
Subject: {email_subject}
Body:
\"\"\"
{clean_body}
\"\"\"

INSTRUCTIONS:
1. Identify the **Product Model** (e.g., GE150, F15i, Prime P1). If unclear, use "Unknown".
2. Determine the **Intent**:
   - "Technical Support": User has a problem or question about usage.
   - "Firmware Update": Specific issues with updating.
   - "Warranty/Repair": Hardware is broken or needs return.
   - "Sales/Stock": Asking about price or availability.
   - "Spam": Unrelated ads, SEO spam, or system notifications.
   - "Gratitude": Pure thank you email with no new questions.
   - "Other": Anything else.
3. Assess **Urgency**: "High" (Angry, System Down, Refund threat), "Medium", "Low".
4. Analyze **Sentiment**: "Positive", "Neutral", "Negative".
5. Extract **Key Issues**: A list of 1-3 short strings summarizing the problem (e.g. ["PC not detecting USB", "Update failed"]).
6. Detect **Language**: The language code of the email (e.g., "en", "zh", "es").

RESPONSE FORMAT:
Return ONLY a valid JSON object.
"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful data extraction assistant. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            self.logger.info(f"AI Content Analysis: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error analyzing email content: {e}")
            return {
                "product_model": "Unknown",
                "intent": "Technical Support",
                "urgency": "Medium",
                "sentiment": "Neutral",
                "key_issues": [f"Error: {str(e)}"],
                "language": "en"
            }

    def analyze_email_intent(self, email_subject, email_body):
        # Legacy wrapper for backward compatibility during migration
        analysis = self.analyze_email_content(email_subject, email_body)
        intent = analysis.get("intent", "Other")
        needs_reply = intent not in ["Spam", "Gratitude"]
        return {"needs_reply": needs_reply, "reason": f"Intent is {intent}"}


    def generate_email_draft(self, context, tools=None, tool_map=None):
        """
        Generate an email draft based on the provided context, optionally using tools.
        
        Args:
            context (dict): Dictionary containing:
                - customer_email: The original email content
                - product_model: Identified product model
                - issue_category: Identified issue category
                - manual_info: Relevant info extracted from manual (optional)
                - template_content: The matched template content (optional)
            tools (list): List of tool definitions (JSON schema)
            tool_map (dict): Mapping of tool names to functions
                
        Returns:
            str: Generated email response, or None if generation failed
        """
        if not self.enabled or not self.client:
            return None
            
        try:
            prompt = self._construct_prompt(context)
            
            messages = [
                {"role": "system", "content": """You are a professional, helpful, and empathetic customer support agent for MOOER Audio. Your goal is to write clear, accurate, and polite email responses in English.

CRITICAL RULES FOR TECHNICAL SUPPORT:
1. DO NOT GUESS or hallucinate technical procedures.
2. When asked about firmware updates, factory resets, or specific features, you MUST use the `search_product_manual` tool to find the exact steps for that specific model.
3. If the user provides a model alias (e.g., 'F15i'), treat it as the official model name (e.g., 'F15i') when searching.
4. If the manual search returns specific instructions (like "click connection switch" or "hold footswitches"), USE THEM EXACTLY.
5. If the manual search results are empty or do not contain the answer, ADMIT IT. Say "I could not find the specific update procedure in the manual" and ask the user for more details. DO NOT default to generic instructions (like "Hold SELECT") unless the manual explicitly says so.
"""},
                {"role": "user", "content": prompt}
            ]
            
            # Initial API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.7,
                max_tokens=1000
            )
            
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls
            
            # Check if the model wants to call a function
            if tool_calls:
                # Add the model's response (with tool calls) to conversation
                messages.append(response_message)
                
                # Execute each tool call
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    self.logger.info(f"AI executing tool: {function_name} with args: {function_args}")
                    
                    if tool_map and function_name in tool_map:
                        function_to_call = tool_map[function_name]
                        try:
                            function_response = function_to_call(**function_args)
                        except Exception as e:
                            function_response = f"Error executing tool: {str(e)}"
                    else:
                        function_response = f"Error: Tool {function_name} not found"
                        
                    # Add tool result to conversation
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_response),
                    })
                
                # Call the API again to get the final response
                second_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000
                )
                generated_content = second_response.choices[0].message.content.strip()
            else:
                generated_content = response_message.content.strip()
            
            # Post-process to remove Markdown if present
            generated_content = self._strip_markdown(generated_content)
            
            self.logger.info("Successfully generated AI response")
            return generated_content
            
        except Exception as e:
            self.logger.error(f"Error generating AI response: {e}")
            return None

    def _strip_markdown(self, text):
        """Remove Markdown formatting from text"""
        # Remove bold/italic markers
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'\*(.*?)\*', r'\1', text)
        text = re.sub(r'__(.*?)__', r'\1', text)
        text = re.sub(r'_(.*?)_', r'\1', text)
        
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).replace('```', ''), text)
        text = re.sub(r'`(.*?)`', r'\1', text)
        
        # Remove headers
        text = re.sub(r'^#+\s+(.*?)$', r'\1', text, flags=re.MULTILINE)
        
        return text

    def _construct_prompt(self, context):
        """Construct the prompt for the LLM"""
        customer_email = context.get('customer_email', '')
        product_model = context.get('product_model', 'MOOER Product')
        manual_info = context.get('manual_info', '')
        template_content = context.get('template_content', '')
        
        prompt = f"""
Please draft a professional customer support email response for MOOER Audio.

CONTEXT:
- Product: {product_model}
- Customer's Email:
\"\"\"
{customer_email}
\"\"\"

RELEVANT KNOWLEDGE (from Manual):
\"\"\"
{manual_info}
\"\"\"

SUGGESTED TEMPLATE/POLICY (Reference only, adapt as needed):
\"\"\"
{template_content}
\"\"\"

INSTRUCTIONS:
1. Be polite, professional, and helpful. Start with "Dear customer,".
2. Address the customer's specific issue directly using the Knowledge provided.
3. If the Manual Knowledge answers the question, explain it clearly in simple steps.
4. If the Template suggests a specific policy (like warranty or Amazon return), make sure to include those key details (e.g., asking for order ID or SN).
5. Tone: Empathetic and technical but accessible.
6. Sign off with "Best regards,\nMOOER Support Team".
7. Do not include placeholders like [Insert Name] unless you can infer them.
8. OUTPUT FORMAT: Plain text only. Do NOT use Markdown (no **bold**, *italics*, or `code blocks`).
"""
        return prompt

if __name__ == "__main__":
    # Test the AI Handler
    logging.basicConfig(level=logging.INFO)
    handler = AIHandler()
    if handler.enabled:
        test_context = {
            "customer_email": "My GE150 is not turning on. I tried different cables.",
            "product_model": "GE150",
            "manual_info": "Troubleshooting: Check power supply. Ensure 9V DC center negative.",
            "template_content": "If the unit is defective, please contact the seller."
        }
        print(handler.generate_email_draft(test_context))
    else:
        print("AI Handler is disabled or not configured.")
