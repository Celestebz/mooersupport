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
        self.last_requires_human_review = False
        self.last_human_review_reason = ""
        self.last_human_review_label = ""
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
                "mail_category": str,
                "issue_category": str,
                "reply_template_category": str,
                "classification_confidence": float,
                "classification_reason": str,
                "evidence": list,
                "needs_human_review": bool,
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
                "mail_category": "technical_support",
                "issue_category": "unknown_issue",
                "reply_template_category": "manual_human_reply",
                "classification_confidence": 0.0,
                "classification_reason": "AI unavailable; fallback classification only",
                "evidence": [],
                "needs_human_review": True,
                "urgency": "Medium",
                "sentiment": "Neutral",
                "key_issues": ["AI Unavailable"],
                "language": "en"
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
   - GE100 is DIFFERENT from GE100 Pro and GE100 Pro Li! They are COMPLETELY different products with different hardware, features, and manuals. DO NOT confuse them.
   - GE100 Pro is DIFFERENT from GE100 Pro Li! GE100 Pro Li has a built-in lithium battery, GE100 Pro does not. They share a manual but are different hardware variants.
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
   GE series: GE100, GE100 Pro, GE100 Pro Li, GE150, GE150 Pro, GE150 Plus, GE150 MAX, GE200, GE200 Pro, GE200 PLUS Li, GE250, GE300, GE300 Lite, GE1000
   Prime series: Prime P1, Prime P2, Prime M1, Prime M2
   GL series: GL100, GL200
   GS series: GS1000, GS1000Li
   SD series: SD10i, SD30i, SD50A, SD50B, SD75
   F series: F15i, F15i Li, F40i
   Others: GTRS 800, GTRS 900, Radar, Preamp Live, Ocean Machine, Red Truck, Black Truck, Hornet, Drummer X2, Loopation, GWF4, PE100, Tone Capture, PCL6 MKII

5. PRODUCT COLOR / VARIANT FACTS (CRITICAL - do not guess or make up color options):
   - GE100 Pro (non-Li, standard power): WHITE only
   - GE100 Pro Li (lithium battery-powered): BLACK only
   - GS1000 (non-Li, standard power): WHITE only
   - GS1000Li (lithium battery-powered): BLACK only
   - Rule: Li (battery) version = Black; Non-Li version = White (applies to GE100 Pro and GS1000 lines)
   - If a customer asks about a color not listed above (e.g., "white GE100 Pro Li"), tell them that color is not available for that variant.

6. EMAIL CONTEXT RULES:
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
   - CRITICAL: If email mentions "GE100 Pro Li", product is "GE100 Pro Li" (NOT "GE100" or "GE100 Pro")
   - CRITICAL: If email mentions "GE100 Pro" (without "Li"), product is "GE100 Pro" (NOT "GE100" or "GE100 Pro Li")
   - CRITICAL: If email ONLY mentions "GE100" (no "Pro"), product is "GE100" (NOT "GE100 Pro" or "GE100 Pro Li")
   - CRITICAL: If subject contains "GE1000", product is GE1000 (not GL100)
   - CRITICAL: If subject contains "GE300", product is GE300 (not GS1000)
   - Only use "Unknown" if NO model is mentioned at all
2. Determine the **Intent**:
   - "Technical Support": User has a problem or question about usage.
   - "Firmware Update": Specific issues with updating.
   - "Warranty/Repair": Hardware is broken or needs return.
   - "Sales/Stock": Asking about price or availability.
   - "Spam": Clearly unrelated ads or SEO spam.
   - "System Notification": Delivery failures, automated mailbox/system messages, or machine-generated notices.
   - "Gratitude": Pure thank you email with no new questions.
   - "Partnership/Collaboration": Business proposals, artist endorsements, distribution inquiries.
   - "Press/Media": Interview requests, press releases, review requests.
   - "Dealer Inquiry": Questions about becoming a dealer or wholesale.
   - "Other": Anything else.
3. Assess **Urgency**: "High" (Angry, System Down, Refund threat), "Medium", "Low".
4. Analyze **Sentiment**: "Positive", "Neutral", "Negative".
5. Extract **Key Issues**: A list of 1-3 short strings summarizing the problem.
6. Detect **Language**: The language code (e.g., "en", "zh", "es").
7. Extract structured issue facts from the customer's CURRENT message. Do not let quoted history override the new message.
   Return issue_facts as an object:
   - product_model: exact product from the current issue when present
   - action: e.g. firmware_update, app_connection, audio_output, warranty_repair, software_driver
   - failure_stage: e.g. progress_0_percent, progress_19_percent, after_update, startup, normal_use
   - symptoms: e.g. comp_button_flashing, update_error, freeze_after_update, distorted_sound, no_output
   - versions: firmware/software versions explicitly mentioned
   - platforms: OS/USB/app/computer details explicitly mentioned
   - evidence: 1-2 short evidence snippets from the email
   - possible_different_issue_reasons: why this may NOT be the same as a broader category
   Return issue_fingerprint as a stable snake_case phrase, for example:
   firmware_update_failed_progress_or_error, firmware_update_freeze_after_update,
   software_old_version_or_backup_request, software_window_display_or_scaling,
   audio_output_noise_or_distortion.
8. Choose stable support-system classifications. You MUST choose from these exact values:

mail_category:
- technical_support
- firmware_update
- warranty_repair
- parts_purchase
- registration_account
- sales_stock
- feedback_suggestion
- complaint
- customer_followup_ack
- business_media
- spam_irrelevant
- system_notification
- unclassified

issue_category:
- app_version_too_low_connection_failure
- app_usb_bluetooth_connection
- firmware_update_failed
- audio_output_noise
- gs1000_balance_output_issue
- screen_led_hardware
- software_install_driver
- registration_binding_account
- battery_charging_power
- parts_quote_shipping
- usage_midi_looper_preset
- purchase_stock_channel
- warranty_repair_process
- business_sales_media
- spam_irrelevant
- unknown_issue

reply_template_category:
- troubleshooting_steps
- firmware_instruction
- comfort_ack_wait_solution
- known_solution_reply
- request_more_info
- warranty_process
- parts_quote_or_request_evidence
- app_connection_instruction
- account_registration_instruction
- escalate_to_sales_media
- manual_human_reply
- no_customer_reply

AI-FIRST CLASSIFICATION RULES:
- The AI classification is the primary classification. Do not rely on a single keyword if the context says otherwise.
- Do NOT mark "Gratitude" or customer acknowledgement as no-reply if the email contains any new issue, follow-up, complaint, missing answer, or unresolved problem.
- If an email is a distributor/internal forward but includes a real customer product issue, classify the product issue and set needs_human_review=true instead of suppressing it.
- If you are unsure, use unclassified/unknown_issue/manual_human_reply and set needs_human_review=true.
- Product, issue_category, and issue_fingerprint must be supported by evidence from the current customer message or subject. If a product appears only in quoted history, lower confidence and set needs_human_review=true.
- Separate similar-looking firmware issues: update progress/error, freeze after update, old software/version request, and desktop software display problems are different issue facts unless the email explicitly connects them.
- For iAMP family products (F15i, F40i, SD10i, SD30i, iAMP), if the current message says the app/application/version is "too low" or "to low", asks the customer to update even though the latest app was installed, or mentions iAMP app 1.6.0 after the June 11 update, use issue_category=app_version_too_low_connection_failure and issue_fingerprint=app_version_too_low_connection_failure. Do not classify this as firmware_update_failed unless firmware update progress/error is explicitly described.
- Return evidence as 1-3 short snippets copied or paraphrased from the email that justify the classification.
- classification_confidence must be a number from 0.0 to 1.0. Use <0.65 when the classification needs human review.

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
                "mail_category": "technical_support",
                "issue_category": "unknown_issue",
                "reply_template_category": "manual_human_reply",
                "classification_confidence": 0.0,
                "classification_reason": f"AI error: {str(e)}",
                "evidence": [],
                "needs_human_review": True,
                "urgency": "Medium",
                "sentiment": "Neutral",
                "key_issues": [f"Error: {str(e)}"],
                "language": "en"
            }

    def analyze_email_intent(self, email_subject, email_body):
        # Legacy wrapper for backward compatibility during migration
        analysis = self.analyze_email_content(email_subject, email_body)
        intent = analysis.get("intent", "Other")
        needs_reply = intent not in ["Spam", "System Notification"]
        return {"needs_reply": needs_reply, "reason": f"Intent is {intent}"}

    def _reset_generation_flags(self):
        self.last_requires_human_review = False
        self.last_human_review_reason = ""
        self.last_human_review_label = ""

    def _mark_human_review(self, reason, label="Knowledge Gap - Needs Human"):
        self.last_requires_human_review = True
        self.last_human_review_reason = reason or "Knowledge base did not contain a confirmed answer"
        self.last_human_review_label = label or "Knowledge Gap - Needs Human"

    def _build_internal_check_ack(self):
        return (
            "Dear customer,\n\n"
            "Thank you for contacting MOOER Support.\n\n"
            "We have received your question. I could not find a confirmed answer in our current support knowledge base, "
            "so I have forwarded your case to our support team for further checking. We will confirm the details internally "
            "and get back to you as soon as possible.\n\n"
            "Best regards,\n"
            "MOOER Support Team"
        )

    def _tool_result_requires_human_review(self, function_name, function_response):
        text = str(function_response or "")
        lowered = text.lower()
        if function_name == "escalate_to_human" or "escalation_triggered" in lowered:
            return text.replace("ESCALATION_TRIGGERED:", "").strip() or "AI requested human review"
        if "knowledge_not_found" in lowered:
            return text.replace("KNOWLEDGE_NOT_FOUND:", "").strip()
        return ""


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
            self._reset_generation_flags()
            prompt = self._construct_prompt(context)
            
            messages = [
                {"role": "system", "content": """You are a concise, musician-friendly support agent for MOOER Audio. Your goal is to write clear, accurate, natural email responses in English for guitarists, bassists, producers, and live/recording musicians.

MUSICIAN-FRIENDLY STYLE:
- Keep the reply short by default: 80-150 words for ordinary cases. Go longer only when a confirmed technical procedure needs numbered steps.
- Start with "Dear customer," and move quickly into the answer or next action.
- Sound like a real support person who understands gear, firmware, presets, outputs, signal, editors, and live/recording use. Do not overdo slang.
- Avoid generic AI support phrasing such as "I understand how frustrating...", "we are happy to assist...", "thank you for bringing this to our attention", and long empathy paragraphs.
- For technical issues, prefer a short conclusion plus 3-5 actionable steps. Do not add background explanations unless they prevent a wrong action.
- Use exactly one greeting and one sign-off. Do not add a second thank-you, greeting, or sign-off if the provided template already includes one.
- Preserve approved template wording exactly when it appears in the template, but do not repeat it elsewhere in the draft.
- Existing support templates may contain approved team wording like "Thank you for choosing our products—we truly appreciate your support!" or "Thanks again and have a nice day!" Keep that wording when it is part of the template, but do not duplicate it.

CRITICAL PRODUCT KNOWLEDGE - MOOER CLOUD ACCOUNT:
- Phone number registration currently only supports mainland China (+86) phone numbers.
- Overseas users (non-China phone numbers) MUST register using EMAIL instead of phone number.
- When a customer reports they cannot register due to country code issues, instruct them to use email registration.

CRITICAL RULES FOR HARDWARE REPAIR / PARTS REPLACEMENT:
1. Determine warranty status FIRST: ask for purchase date. If within 1 year → warranty repair is FREE but customer pays round-trip shipping. If expired → customer pays repair + labor + round-trip shipping.
2. If a customer reports a hardware issue (screen not working, LCD backlight dead, broken display, battery failure, etc.) and PART PRICE INFO is available in the prompt below — QUOTE THE EXACT PRICE.
3. Offer TWO paths:
   a) Buy the replacement part (self-install): Quote price + ask for FULL SHIPPING ADDRESS to calculate shipping cost. DO NOT give a shipping quote without the address.
   b) Send the unit to MOOER for repair: Customer pays round-trip shipping. If within warranty, repair is free. If out of warranty, customer also pays repair cost + labor. Total quoted after inspection.
4. If the customer chooses option (a), you MUST collect: full name, street address, city, state/province, postal code, country, phone number.
5. CRITICAL: Never promise a shipping cost until you have the complete address. Shipping cost varies by destination.

CRITICAL RULES FOR TECHNICAL SUPPORT:
1. DO NOT GUESS or hallucinate technical procedures.
2. When asked about firmware updates, factory resets, or specific features, you MUST use the `search_product_manual` tool to find the exact steps for that specific model.
3. If the user provides a model alias (e.g., 'F15i'), treat it as the official model name (e.g., 'F15i') when searching.
4. If the manual search returns specific instructions (like "click connection switch" or "hold footswitches"), USE THEM EXACTLY.
5. If the manual search results are empty or do not contain the answer:
   - DO NOT invent steps, settings, prices, URLs, compatibility facts, or troubleshooting procedures.
   - DO NOT use general product knowledge as a substitute for a confirmed support source.
   - Use `escalate_to_human` or write only a brief acknowledgement that the case will be checked internally.
   - The customer-facing acknowledgement must not include unverified technical advice.

CRITICAL RULES FOR MOOER OFFICIAL DOWNLOADS:
- Owner's manuals are found on each product's own page on the MOOER official website, inside that product page's Download section.
- Do NOT tell customers to use a generic Support/Downloads page for owner's manuals.
- Do NOT provide https://www.mooeraudio.com/pages/download as a direct manual link.
- Firmware files, editors, drivers, and software installation packages are downloaded from https://www.mooeraudio.com/companyfile/Downloads-1.
- Always distinguish owner's manuals from firmware/software downloads. Do not send a firmware/software package URL when the customer asks only for an owner's manual, and do not send product-page manual instructions when the customer asks for firmware, drivers, editors, or installation packages.
- When using `check_official_downloads`, set download_type="owners_manual" for manual/user-guide requests and download_type="firmware_software" for firmware, editor, driver, app, or installer package requests. Use download_type="auto" only when the customer's request is ambiguous.
- If you do not have the exact product-page URL, give navigation steps instead of inventing a URL.
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

                    human_review_reason = self._tool_result_requires_human_review(function_name, function_response)
                    if human_review_reason:
                        self._mark_human_review(human_review_reason)
                        
                    # Add tool result to conversation
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_response),
                    })

                if self.last_requires_human_review:
                    self.logger.info(
                        "Knowledge lookup requires human review: %s",
                        self.last_human_review_reason,
                    )
                    return self._build_internal_check_ack()

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

            if generated_content:
                self._log_style_warnings(generated_content)

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

    def _log_style_warnings(self, text):
        """Log musician-friendly style risks without rewriting approved templates."""
        if not text:
            return

        lowered = text.lower()
        body_text = re.sub(
            r"^(dear customer,|hello,|hi,|hi there,|dear .{1,80},)\s*",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        body_text = re.sub(
            r"(best regards,|kind regards,|sincerely,|mooer support team)[\s\S]*$",
            "",
            body_text,
            flags=re.IGNORECASE,
        ).strip()
        word_count = len(re.findall(r"\b[\w'-]+\b", body_text))

        style_patterns = [
            "i understand how frustrating",
            "we are happy to assist",
            "thank you for bringing this to our attention",
            "please rest assured",
            "we truly understand",
            "we appreciate your patience and understanding",
        ]
        matched_patterns = [pattern for pattern in style_patterns if pattern in lowered]

        greeting_count = len(re.findall(r"\b(dear customer|hello|hi there)\b", lowered))
        signoff_count = len(re.findall(r"\b(best regards|kind regards|sincerely|mooer support team)\b", lowered))

        if word_count > 180:
            self.logger.warning("STYLE WARNING - draft may be too long for musician-friendly default: %s words", word_count)
        if matched_patterns:
            self.logger.warning("STYLE WARNING - canned support phrasing detected: %s", ", ".join(matched_patterns))
        if greeting_count > 1 or signoff_count > 2:
            self.logger.warning(
                "STYLE WARNING - possible duplicate greeting/sign-off: greetings=%s signoffs=%s",
                greeting_count,
                signoff_count,
            )

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
            r"^The manual search",
            r"^The manual search returned results",
            r"^The search returned results",
            r"^The search did not",
            r"^The manual did not",
            r"^Based on the search results",
            r"^Based on my general knowledge",
            r"^However, based on my general knowledge",
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
        conversation_context = context.get('conversation_context', '')
        warranty_info = context.get('warranty_info', '')
        distributor_info = context.get('distributor_info', '')
        issue_category = context.get('issue_category', '')
        part_price_info = context.get('part_price_info', None)
        is_price_inquiry = context.get('is_price_inquiry', False)
        part_name = context.get('part_name', '')

        # Build template section
        if template_content:
            template_section = (
                "SUGGESTED TEMPLATE (trusted support wording/facts; keep the core wording, "
                "fill only what is needed, and do not expand it into a long email):\n"
                f"{template_content}"
            )
        else:
            template_section = "SUGGESTED TEMPLATE: No specific template is available."

        # Build part price section
        price_section = ""
        template_fill_instruction = ""
        if is_price_inquiry:
            if part_price_info:
                if 'all_prices' in part_price_info:
                    # 多配件价格
                    prices_list = ", ".join([f"{k}: ${v}" for k, v in part_price_info['all_prices'].items()])
                    price_section = f"\n\nPART PRICE INFO (OFFICIAL QUOTE - MUST use these exact prices):\nAvailable prices for {product_model}: {prices_list}\n"
                    template_fill_instruction = "\nCRITICAL: You have OFFICIAL part prices above. QUOTE THE EXACT PRICE to the customer. DO NOT say \"we need to check with our internal team\" — the price IS above. State the price clearly.\n"
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
CONVERSATION HISTORY CONTEXT:
{conversation_context if conversation_context else "No prior thread context was provided."}

CUSTOMER'S QUESTION (Read carefully!):
---
{customer_email}
---

MANUAL KNOWLEDGE (if available):
{manual_info}

MOOER WARRANTY POLICY (CRITICAL - Follow exactly):
{warranty_info}

MOOER DISTRIBUTOR LIST (Official - Use when customer asks where to buy):
{distributor_info}

{template_section}

CRITICAL INSTRUCTIONS:
1. READ THE CUSTOMER'S EMAIL ABOVE - Understand what they are asking!
1a. Use CONVERSATION HISTORY CONTEXT to understand short follow-ups like "Any update?", "still not working", or "same issue". Do not repeat questions already answered in the timeline evidence.
2. Start with "Dear customer,".
3. Use only confirmed support sources provided in this prompt or returned by tools: manual knowledge, official policy, distributor data, official part prices, solved issue templates, or suggested templates.
4. If the confirmed sources do not answer the customer's question, do not invent an answer and do not use general knowledge. Reply only that the case will be checked internally and the support team will get back to the customer.
5. Do not ask for more details unless a confirmed policy or template specifically requires it.
6. Do not provide best-effort troubleshooting unless it is supported by confirmed sources in this prompt or tool results.
7. MUSICIAN-FRIENDLY STYLE:
   - Default to 80-150 words, excluding greeting and sign-off.
   - First paragraph should answer the issue or state the next action, not repeat generic thanks.
   - Avoid canned AI phrases: "I understand how frustrating...", "we are happy to assist...", "thank you for bringing this to our attention", "please rest assured", and long apology/comfort paragraphs.
   - For technical replies, use short numbered steps and practical gear language such as unit, editor, firmware, preset, output, signal, or USB connection when relevant.
   - If a template sentence contains approved team wording, preserve it as written in the template instead of rephrasing or repeating it.
   - Keep existing approved template wording if present, including team phrases like "Thank you for choosing our products—we truly appreciate your support!" and "Thanks again and have a nice day!"
   - Do not duplicate a template greeting, thank-you sentence, or sign-off. The final email must contain only one greeting and one sign-off.
8. Sign off with "Best regards,
MOOER Support Team"
9. Plain text only. No Markdown.
10. Never output tool call markup, XML, JSON, DSML, or function-call text in the final email. The final answer must be only the customer-facing email body.
11. WARRANTY RULE: MOOER warranty is exactly 1 year. If customer mentions a purchase date, calculate: purchase_date + 1 year. If that date is in the past, warranty IS EXPIRED. Do NOT say "likely still within warranty" unless you have verified the date. If expired, offer out-of-warranty paid repair service.
12. DISTRIBUTOR RULE: When a customer asks "where can I buy", "where to purchase", or any question about availability in their region — CHECK the MOOER DISTRIBUTOR LIST above FIRST. If a distributor exists for their country, provide the distributor name, website, and contact info. If no distributor is listed for their country, suggest they check Amazon or contact us for the nearest distributor. NEVER say "we don't have this information" if the distributor IS listed above.
13. NO FAKE PRICING: When you direct a customer to a distributor, DO NOT mention pricing at all. Do not say "we will check with our internal team for pricing" or "we'll get back to you with the price." The distributor handles pricing — tell the customer to contact the distributor for pricing and availability. Only mention pricing if the customer explicitly asks for a price quote AND there is no relevant distributor.
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
