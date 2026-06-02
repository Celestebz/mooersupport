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

    def analyze_email_content(self, email_subject, email_body, cc_list=None, sender_email=None):
        """
        Analyze email content to extract structured information using AI.

        Args:
            email_subject: Email subject line
            email_body: Email body content
            cc_list: List of CC email addresses (optional)
            sender_email: Sender's email address (optional)

        Returns:
            dict: {
                "product_model": str,
                "intent": str,
                "urgency": str,
                "sentiment": str,
                "key_issues": list,
                "language": str,
                "email_type": str  # product_related, non_product, being_processed, other
            }
        """
        if not self.enabled or not self.client:
            return {
                "product_model": "Unknown",
                "intent": "Technical Support",
                "urgency": "Medium",
                "sentiment": "Neutral",
                "key_issues": ["AI Unavailable"],
                "language": "en",
                "email_type": "other"
            }
            
        try:
            clean_body = email_body[:3000] # Increased context window

            # Add CC and sender context to prompt
            cc_context = f"\nCC: {', '.join(cc_list)}" if cc_list else "\nCC: None"
            sender_context = f"\nFrom: {sender_email}" if sender_email else "\nFrom: Unknown"

            prompt = f"""You are an expert content analyzer for Mooer Audio customer support.
Analyze the following email and extract structured data.

IMPORTANT - PRODUCT MODEL RULES (STRICT):
1. OFFICIAL MODEL NAMING - Use these EXACT formats with proper spacing:
   - "GE150" not "GE150Pro" or "GE 150"
   - "GE150 Pro" not "GE150Pro" (space required)
   - "GE150 Plus" not "GE150Plus" (space required)
   - "GE150 MAX" not "GE150 Max" (ALL CAPS for MAX)
   - "GE200" not "GE 200"
   - "GE200 Pro" not "GE200Pro" (space required)
   - "GE200 PLUS Li" not "GE200 PLUSLi" (space required)
   - "GE250" not "GE 250"
   - "GE300" not "GE 300"
   - "GE300 Lite" not "GE300Lite" (space required)
   - "GE1000" not "GE 1000"
   - "GE100" not "GE 100"
   - "Prime P1" not "P1 Prime" or "PrimeP1"
   - "Prime P2" not "P2 Prime" or "PrimeP2"
   - "Prime M1" not "M1 Prime"
   - "Prime M2" not "M2 Prime"
   - "GL100" not "GE100" (GL100 is looper, GE100 is multi-effects)
   - "GL200" not "GE200" (GL200 is looper, GE200 is multi-effects)
   - "GS1000" not "GE1000" or "GE300"
   - "GS1000Li" not "GS1000 Li"
   - "F15i" not "F15 i"
   - "F15i Li" not "F15iLi" or "F15 Li"
   - "F40i" not "F40 i"

2. EASY TO CONFUSE PRODUCTS - BE VERY CAREFUL:
   - GE1000 is DIFFERENT from GL100! GE1000 is guitar multi-effects, GL100 is looper
   - GL200 is DIFFERENT from GE150/GE200! GL200 is looper, GE150/GE200 are multi-effects
   - GS1000 is DIFFERENT from GE300! They are completely different models
   - Prime P2 is DIFFERENT from GE series - separate product lines
   - GE300 Lite is DIFFERENT from GL200!
   - SD10i/SD30i/SD50A are DIFFERENT from each other

3. INVALID/NON-EXISTENT MODELS - If you see these, treat as Unknown:
   - "GE001", "GE-100", "GE 100" (should be GE100)
   - "F4 White Prime P1" (does not exist, should be F4 White or Prime P1)
   - "iAMP AI" (does not exist, should be iAMP series)
   - Any model number that doesn't match the official list below

4. OFFICIAL MOOER PRODUCT LIST (use these exact names):
   GE series: GE100, GE150, GE150 Pro, GE150 Plus, GE150 MAX, GE200, GE200 Pro, GE200 PLUS Li, GE250, GE300, GE300 Lite, GE1000
   Prime series: Prime P1, Prime P2, Prime M1, Prime M2
   GL series: GL100, GL200
   GS series: GS1000, GS1000Li
   SD series: SD10i, SD30i, SD50A, SD50B, SD75
   F series: F15i, F15i Li, F40i
   Others: GTRS 800, GTRS 900, Radar, Preamp Live, Ocean Machine, Red Truck, Black Truck, Hornet, Drummer X2, Loopation, GWF4, PE100, Tone Capture, PCL6 MKII

5. EMAIL CONTEXT RULES:
   - If subject mentions a specific model (e.g., "GE1000", "GL200"), that is the product
   - For REPLY emails, look at BOTH new message AND quoted original message
   - If email is NOT about a specific product (partnership, spam, etc.), use "Unknown"

EMAIL INFO:
Subject: {email_subject}
Body:
{clean_body}
{sender_context}
{cc_context}

INSTRUCTIONS:
1. Identify the **Product Model** using the rules above.
   - CRITICAL: Use EXACT naming from official product list
   - CRITICAL: If subject contains "GE1000", product is GE1000 (not GL100)
   - CRITICAL: If subject contains "GE300", product is GE300 (not GS1000)
   - Only use "Unknown" if NO model is mentioned at all
2. Determine the **Intent**:
   - "Technical Support": User has a problem or question about usage.
   - "Firmware Update": Specific issues with updating.
   - "Warranty/Repair": Hardware is broken or needs return.
   - "Sales/Stock": Asking about price or availability.
   - "Spam": Unrelated ads, SEO spam, or system notifications.
   - "Gratitude": Pure thank you email with no new questions.
   - "Partnership/Collaboration": Business proposals, artist endorsements, distribution inquiries.
   - "Press/Media": Interview requests, press releases, review requests.
   - "Dealer Inquiry": Questions about becoming a dealer or wholesale.
   - "Other": Anything else.
3. Assess **Urgency**: "High" (Angry, System Down, Refund threat), "Medium", "Low".
4. Analyze **Sentiment**: "Positive", "Neutral", "Negative".
5. Extract **Key Issues**: A list of 1-3 short strings summarizing the problem.
6. Detect **Language**: The language code (e.g., "en", "zh", "es").
7. Determine **Email Type**:
   - "product_related": Customer/end-user asking about a MOOER product they own
   - "non_product": NOT about specific product (partnership, spam, press, dealer, thank you with no issue)
   - "being_processed": Internal team forwarding/CC'ing for info, not expecting new response
   - "other": Cannot determine

RESPONSE FORMAT:
Return ONLY a valid JSON object.
"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful data extraction assistant. Output valid JSON only, no markdown code blocks."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )

            result_text = response.choices[0].message.content.strip()
            
            # Clean up potential markdown code blocks (```json ... ```)
            if result_text.startswith("```"):
                result_text = result_text.replace("```json", "").replace("```", "").strip()
            
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback: try to find JSON object within text
                match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                else:
                    raise ValueError(f"Could not parse JSON from AI response: {result_text}")
            
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
                "language": "en",
                "email_type": "other"
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
5. If the manual search results are empty or do not contain the answer:
   - DO NOT give up or return an empty response.
   - ADMIT that the specific manual instruction was not found.
   - USE YOUR GENERAL TECHNICAL KNOWLEDGE to offer helpful, safe troubleshooting steps relevant to the user's issue (e.g., for MIDI issues: check channels, cables, USB host capability).
   - Politely ask for more details if needed.
   - NEVER default to generic "Please contact support" templates if you can offer a sensible technical suggestion first.
   - IMPORTANT: You have **ONLY ONE CHANCE** to search. If the search result is not perfect, DO NOT say "Let me search again". Instead, use the partial info and your general knowledge to provide the best possible troubleshooting advice immediately.
"""},
                {"role": "user", "content": prompt}
            ]
            
            # Initial API call
            self.logger.info(f"Calling API with model: {self.model}, tools: {tools is not None}")
            self.logger.debug(f"Prompt: {prompt[:500]}...")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.7
            )

            self.logger.info(f"API Response: {response}")
            self.logger.info(f"Response choices count: {len(response.choices)}")

            response_message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            raw_first = response_message.content
            self.logger.info(f"First response - content type: {type(raw_first)}, is None: {raw_first is None}, repr: {repr(raw_first)[:200] if raw_first else 'EMPTY'}, tool_calls: {response_message.tool_calls}")
            self.logger.info(f"AI Initial Response. Finish reason: {finish_reason}")

            tool_calls = response_message.tool_calls

            # Check if the model wants to call a function
            if tool_calls:
                # Add the model's response (with tool calls) to conversation
                assistant_msg_dict = {
                    "role": response_message.role,
                    "content": response_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in response_message.tool_calls
                    ]
                }
                messages.append(assistant_msg_dict)

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
                self.logger.info(f"Second API call - messages count: {len(messages)}")
                second_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7
                )

                # Debug: log second response details
                second_message = second_response.choices[0].message
                raw = second_message.content
                self.logger.info(f"Second response - content type: {type(raw)}, is None: {raw is None}, repr: {repr(raw)[:200] if raw else 'EMPTY'}, tool_calls: {second_message.tool_calls}")

                # Handle potential None content for tool-call response
                raw_content = second_response.choices[0].message.content
                if raw_content is None:
                    self.logger.error("API returned None content")
                    generated_content = ""
                else:
                    generated_content = raw_content.strip()

                self.logger.info(f"AI Final Response. Finish reason: {second_response.choices[0].finish_reason}")

                # DEBUG: Log all tool results for troubleshooting
                for msg in messages:
                    # All messages here should be dicts; guard defensively
                    if isinstance(msg, dict) and msg.get("role") == "tool":
                        self.logger.debug(f"Tool result - {msg.get('name')}: {str(msg.get('content', ''))[:200]}")
            else:
                # Handle potential None content for non-tool-call response
                raw_content = response_message.content
                if raw_content is None:
                    self.logger.error("API returned None content")
                    generated_content = ""
                else:
                    generated_content = raw_content.strip()

                self.logger.info(f"AI Final Response. Finish reason: {finish_reason}")

                # Retry if truncated (length)
                if finish_reason == "length":
                     self.logger.warning("Response truncated due to length. Retrying with higher token limit (though 2500 should be enough)...")
                     pass 
            
            # Post-process to remove Markdown if present
            generated_content = self._strip_markdown(generated_content)
            generated_content = self._remove_tool_markup(generated_content)
            
            # Validation: Check if response is empty or too short
            if not generated_content or len(generated_content) < 50:
                 self.logger.warning(f"Generated content too short ({len(generated_content) if generated_content else 0} chars). Retrying...")
                 # Simple retry logic: just call again once
                 try:
                    retry_response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.8  # Increase temp slightly
                    )
                    retry_content = retry_response.choices[0].message.content
                    if retry_content:
                        generated_content = retry_content.strip()
                        generated_content = self._strip_markdown(generated_content)
                        generated_content = self._remove_tool_markup(generated_content)
                    else:
                        self.logger.error("Retry returned empty content")
                        generated_content = ""
                 except Exception as retry_err:
                     self.logger.error(f"Retry failed: {retry_err}")
                     generated_content = ""

            self.logger.info("Successfully generated AI response")

            # Post-process to remove internal AI thinking that leaked into response
            generated_content = self._filter_ai_thinking(generated_content)
            generated_content = self._remove_tool_markup(generated_content)

            if self._contains_tool_markup(generated_content):
                self.logger.error("AI response still contains tool-call markup after cleanup; rejecting draft")
                return ""

            if generated_content and not self._looks_like_customer_email(generated_content):
                self.logger.error(f"AI response does not look like a customer email; rejecting draft: {generated_content[:200]}")
                return ""

            # DEBUG: Detect generic "need more info" responses
            if generated_content:
                need_info_patterns = [
                    "provide more detail",
                    "provide more information",
                    "need more detail",
                    "need more information",
                    "could you please provide",
                    "please let me know",
                    "need additional information"
                ]
                content_lower = generated_content.lower()
                for pattern in need_info_patterns:
                    if pattern in content_lower:
                        self.logger.warning(f"DETECTED GENERIC RESPONSE - AI asked for more info (pattern: '{pattern}')")
                        self.logger.warning(f"Full response: {generated_content[:500]}")
                        break

            return generated_content
            
        except Exception as e:
            self.logger.error(f"Error generating AI response: {e}")
            return None

    def _contains_tool_markup(self, text):
        """Detect internal tool-call markup that must never be sent to customers."""
        if not text:
            return False

        lowered = text.lower()
        markers = [
            "tool_calls",
            "<tool_call",
            "</tool_call",
            "dsml",
            "<｜｜dsml｜｜",
            "｜｜dsml｜｜",
            "</｜｜dsml｜｜",
            "searchproductmanual",
            "search_product_manual",
            "check_official_downloads",
            "get_firmware_update_guide",
            "escalate_to_human",
        ]
        return any(marker in lowered for marker in markers)

    def _remove_tool_markup(self, text):
        """Remove leaked tool-call blocks from model output."""
        if not text:
            return text

        original_text = text
        # Remove XML/DSML-style tool call blocks, including the full-width pipe
        # delimiters some model gateways emit.
        text = re.sub(r"<\s*[｜|]{0,2}\s*DSML\s*[｜|]{0,2}\s*tool_calls\s*>[\s\S]*?<\s*/\s*[｜|]{0,2}\s*DSML\s*[｜|]{0,2}\s*tool_calls\s*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*tool_calls?\s*>[\s\S]*?<\s*/\s*tool_calls?\s*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<\s*[｜|]{0,2}\s*invoke\b[\s\S]*?<\s*/\s*[｜|]{0,2}\s*invoke\s*>", "", text, flags=re.IGNORECASE)

        # If markup removal left only whitespace, keep it empty so the caller
        # retries instead of saving an internal instruction as a draft.
        text = text.strip()
        if text != (original_text or "").strip():
            self.logger.warning("Removed leaked tool-call markup from AI response")
        return text

    def _looks_like_customer_email(self, text):
        """Basic guard that the final output is a sendable support email."""
        if not text:
            return False

        stripped = text.strip()
        if len(stripped) < 50:
            return False

        if not re.search(r"^(Dear customer,|Hello,|Hi,|Hi there,|Dear .{1,80},)", stripped, re.IGNORECASE):
            return False

        if not re.search(r"(Best regards,|Kind regards,|Sincerely,|MOOER Support Team)", stripped, re.IGNORECASE):
            return False

        return True

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

    def _filter_ai_thinking(self, text):
        """Filter out internal AI thinking/thoughts that leaked into the response"""
        if not text:
            return text

        original_text = text

        # Check if the response starts with internal AI thinking phrases
        # These phrases at the START of the response indicate leaked internal thinking
        thinking_start_patterns = [
            # Search-related thinking
            r"^Let me search for more specific information about",
            r"^Let me search for information about",
            r"^Let me search more specifically for",
            r"^Let me check",
            r"^I'll search for",
            r"^I need to search for",
            r"^Now let me search",
            r"^First, let me",
            r"^Let me find",
            # NEW: Manual/knowledge analysis thinking that leaks into response
            r"^The \w+ manual mentions",
            r"^The \w+ search returned",
            r"^However, the customer",
            r"^However, the user",
            r"^However, they",
            r"^It could be the",
            r"^It might be the",
            r"^This could be the",
            r"^Let me look up",
            r"^Let me verify",
            r"^Based on my search",
            r"^After reviewing",
            # Tool result analysis - these are AI's internal reasoning after calling tools
            r"^The manual search returned results",
            r"^The search returned results",
            r"^Based on the search results",
            r"^Let me use my general knowledge",
            r"^I'll use my general knowledge",
            r"^Using my general knowledge",
            r"^Based on the information provided",
            r"^Looking at the manual",
            r"^According to the manual",
            r"^The manual says",
            r"^I found the following information",
            r"^Let me provide you with",
            # Analysis/reasoning patterns
            r"^I understand that",
            r"^It seems that",
            r"^It appears that",
            # Summary + action patterns (the AI summarizes the issue then says it will draft a response)
            r"^This is a straightforward request",
            r"^This is a simple request",
            r"^This seems like a straightforward",
            r"^This appears to be a",
            r"^This is an easy",
            r"^This looks like a",
            r"^The customer is referring to",
            r"^The customer wants",
            r"^The user is asking",
            r"^The user wants",
            r"^Let me draft",
            r"^I'll draft",
            r"^Here's a draft",
            r"^Below is a draft",
            r"^Here's my draft",
            r"^I will draft",
            r"^Let me write",
            r"^I'll write a response",
            r"^Sure, let me",
            r"^Certainly, let me",
            r"^Okay, I'll",
            r"^Sure, I'll",
        ]

        # First pass: check if response starts with internal thinking
        for pattern in thinking_start_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                # Find where the real content starts (after the thinking)
                # Look for "Dear customer" or similar greeting
                match = re.search(r"(Dear customer,|Hello,|Hi,|Hi there,|Thank you for)", text, re.IGNORECASE)
                if match:
                    text = text[match.start():]
                    self.logger.info(f"Filtered internal AI thinking, found real content at position {match.start()}")
                    break

        # Second pass: also check for thinking patterns anywhere in the text (multi-paragraph thinking)
        # This catches cases like: "The customer is... This is a straightforward... Let me draft... Dear customer,"
        # We need to handle the case where there's thinking between paragraphs
        lines = text.split('\n')
        filtered_lines = []
        found_greeting = False

        for line in lines:
            # Check if this line looks like internal thinking
            is_thinking = False
            for pattern in thinking_start_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    is_thinking = True
                    break

            # Also check for lines that are clearly analysis/summary (don't start with capital letter properly or contain certain keywords)
            if not is_thinking and not found_greeting:
                stripped = line.strip()
                # Skip lines that are clearly not email content (too short, all lowercase, or contain analysis keywords)
                if stripped and len(stripped) < 100 and not stripped.startswith("Dear") and not stripped.startswith("Hello"):
                    # Check for common thinking patterns in middle of text
                    if re.match(r"^(this is|let me|i'll|i need to|basically|essentially|so |now |first )", stripped.lower()):
                        is_thinking = True

            if not is_thinking:
                filtered_lines.append(line)
                # Check if this line contains a greeting
                if re.search(r"(Dear customer,|Hello,|Hi,|Hi there,)", line, re.IGNORECASE):
                    found_greeting = True
            else:
                # If we found greeting, stop filtering (we're past the thinking)
                if found_greeting:
                    filtered_lines.append(line)

        text = '\n'.join(filtered_lines)

        # Also filter if response is mostly internal thinking (short + lowercase start)
        lines = text.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            # If first line is short and doesn't start with greeting
            if len(first_line) < 80 and not first_line.lower().startswith("dear"):
                # Check if it looks like internal thinking
                if re.match(r"^(let me|i'll|i need to|now let me|first let me|checking|searching)", first_line, re.IGNORECASE):
                    # Find first proper sentence
                    for i, line in enumerate(lines):
                        if line.strip().startswith("Dear") or (line.strip() and len(line.strip()) > 20 and line.strip()[0].isupper()):
                            text = '\n'.join(lines[i:])
                            break

        # NEW: If the entire response is internal thinking (no valid content found), return empty
        # This will trigger retry or fallback
        if text.strip():
            first_line = text.strip().split('\n')[0]
            thinking_pattern = r"^(let me|i'll|i need to|now let me|first let me|checking|searching|the \w+ manual|however, the|it could be|it might be)"
            # Check for thinking content even if first line is long
            if re.match(thinking_pattern, first_line, re.IGNORECASE):
                # Check if there's a greeting anywhere in the text
                if not re.search(r"(Dear customer,|Hello,|Hi,|Hi there,|Thank you for)", text, re.IGNORECASE):
                    self.logger.warning(f"Response is entirely internal thinking: {first_line[:80]}...")
                    return ""  # Return empty to trigger retry

        if text != original_text:
            self.logger.info(f"Filtered internal AI thinking from response")

        return text

    def _construct_prompt(self, context):
        """Construct the prompt for the LLM"""
        customer_email = context.get('customer_email', '')
        product_model = context.get('product_model', 'MOOER Product')
        manual_info = context.get('manual_info', '')
        template_content = context.get('template_content', '')
        issue_category = context.get('issue_category', '')
        part_price_info = context.get('part_price_info', None)
        is_price_inquiry = context.get('is_price_inquiry', False)
        part_name = context.get('part_name', '')

        # Build template section
        if template_content:
            template_section = f"SUGGESTED TEMPLATE (Use as reference):\n{template_content}"
        else:
            template_section = "SUGGESTED TEMPLATE: No specific template available - use your knowledge."

        # Build part price section
        price_section = ""
        template_fill_instruction = ""
        if is_price_inquiry:
            if part_price_info:
                if 'all_prices' in part_price_info:
                    # 多配件价格
                    prices_list = ", ".join([f"{k}: ${v}" for k, v in part_price_info['all_prices'].items()])
                    price_section = f"\n\nPART PRICE INFO (For reference):\nAvailable prices for {product_model}: {prices_list}\n"
                else:
                    # 单一配件价格
                    price_section = f"\n\nPART PRICE INFO (Official quote):\n{part_price_info['part_name']} for {product_model}: ${part_price_info['price']} {part_price_info['currency']}\n"
                    # 模板填充指令
                    template_fill_instruction = f"\nIMPORTANT: When using the template, fill in the placeholders:\n- [PRODUCT] = {product_model}\n- [PART NAME] = {part_price_info['part_name']}\n- [PRICE] = {part_price_info['price']}\n"
            else:
                price_section = f"\n\nPART PRICE INFO:\nNo price information available in our database. Please inform the customer that we need to check with our internal team and will respond shortly.\n"
                template_fill_instruction = "\nIMPORTANT: Tell the customer that we need to check with our internal team and will get back to them with the price shortly.\n"

        prompt = f"""Please draft a professional customer support email response for MOOER Audio.

CONTEXT:
- Product: {product_model}
- Issue Category: {issue_category}
{price_section}{template_fill_instruction}
CUSTOMER'S QUESTION (Read carefully!):
---
{customer_email}
---

MANUAL KNOWLEDGE (if available):
{manual_info}

{template_section}

CRITICAL INSTRUCTIONS:
1. READ THE CUSTOMER'S EMAIL ABOVE - Understand what they are asking!
2. Start with "Dear customer,".
3. If Manual Knowledge answers the question, explain it clearly in simple steps.
4. If there is NO relevant Manual Knowledge, use your general knowledge about MOOER products to help.
5. NEVER ask "please provide more details" - you already have their question in the email!
6. If you cannot help, politely explain and offer best-effort troubleshooting.
7. Sign off with "Best regards,
MOOER Support Team"
8. Plain text only. No Markdown.
9. Never output tool call markup, XML, JSON, DSML, or function-call text in the final email. The final answer must be only the customer-facing email body.
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
