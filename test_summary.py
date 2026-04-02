import azure.functions as func
import logging
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient  
from azure.ai.documentintelligence import DocumentIntelligenceClient 
from azure.core.credentials import AzureKeyCredential 
import os, json, random, base64
from azure.cosmos import CosmosClient 
from datetime import datetime 
from concurrent.futures import ThreadPoolExecutor
from azure.identity import DefaultAzureCredential, get_bearer_token_provider 

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="githubrepodocs")
def githubrepodocs(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        # ---------------------------------------------------------------
        # STEP 1: Parse the incoming JSON payload from Power Automate
        # ---------------------------------------------------------------
        try:
            email_payload = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid or missing JSON body"}),
                mimetype="application/json",
                status_code=400
            )

        # Validate required top-level fields
        required_fields = ["subject", "from", "body", "receivedDateTime"]
        missing_fields = [f for f in required_fields if not email_payload.get(f)]
        if missing_fields:
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields in payload: {missing_fields}"}),
                mimetype="application/json",
                status_code=400
            )

        # Extract email fields from payload
        email_from        = email_payload.get("from", "")
        email_subject     = email_payload.get("subject", "")
        email_body        = email_payload.get("body", "")           # HTML body
        email_received_on = email_payload.get("receivedDateTime", "")
        attachments_raw   = email_payload.get("attachments", [])    # May be empty list

        logging.info(f"Email received from: {email_from} | Subject: {email_subject}")
        logging.info(f"Attachments in payload: {len(attachments_raw)}")

        # ---------------------------------------------------------------
        # STEP 2: Get case_id — from query param or JSON body
        # ---------------------------------------------------------------
        case_id = req.params.get('case_id') or email_payload.get('case_id')
        if not case_id:
            return func.HttpResponse(
                json.dumps({"error": "case_id is required (query param or in JSON body)"}),
                mimetype="application/json",
                status_code=400
            )

        logging.info(f"Processing case_id: {case_id}")

        # ---------------------------------------------------------------
        # STEP 3: Load & validate environment variables
        # ---------------------------------------------------------------
        required_env_vars = {
            "BLOB_CONN_STR":           os.getenv("BLOB_CONN_STR"),
            "BLOB_CONTAINER_NAME":     os.getenv("BLOB_CONTAINER_NAME"),
            "DOC_INT_KEY":             os.getenv("DOC_INT_KEY"),
            "DOC_INT_ENDPOINT":        os.getenv("DOC_INT_ENDPOINT"),
            "AZURE_API_ENDPOINT":      os.getenv("AZURE_API_ENDPOINT"),
            "AZURE_API_VERSION":       os.getenv("AZURE_API_VERSION"),
            "COSMOS_CONN_STR":         os.getenv("COSMOS_CONN_STR"),
            "COSMOS_DB_NAME":          os.getenv("COSMOS_DB_NAME"),
            "COSMOS_CONTAINER_NAME":   os.getenv("COSMOS_CONTAINER_NAME"),
            "COSMOS_ENDPOINT":         os.getenv("COSMOS_ENDPOINT")
        }

        missing_vars = [k for k, v in required_env_vars.items() if not v]
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logging.error(error_msg)
            return func.HttpResponse(error_msg, status_code=500)

        logging.info("All environment variables loaded successfully")

        # ---------------------------------------------------------------
        # STEP 4: Initialize Azure clients
        # ---------------------------------------------------------------
        logging.info("Initializing Azure clients...")

        credential     = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )

        blob_service     = BlobServiceClient.from_connection_string(required_env_vars["BLOB_CONN_STR"])
        container_client = blob_service.get_container_client(required_env_vars["BLOB_CONTAINER_NAME"])

        doc_int_client = DocumentIntelligenceClient(
            endpoint=required_env_vars["DOC_INT_ENDPOINT"],
            credential=credential
        )

        aoai_client = AzureOpenAI(
            azure_endpoint=required_env_vars["AZURE_API_ENDPOINT"],
            api_version=required_env_vars["AZURE_API_VERSION"],
            azure_ad_token_provider=token_provider
        )

        cosmos_client = CosmosClient.from_connection_string(required_env_vars["COSMOS_CONN_STR"])
        database      = cosmos_client.get_database_client(required_env_vars["COSMOS_DB_NAME"])
        container     = database.get_container_client(required_env_vars["COSMOS_CONTAINER_NAME"])

        logging.info("All Azure clients initialized successfully")

        # ---------------------------------------------------------------
        # STEP 5: Decode Base64 attachments from payload & upload to Blob
        # ---------------------------------------------------------------
        attachments = []

        if attachments_raw:
            logging.info(f"[ATTACHMENT] Decoding {len(attachments_raw)} attachment(s) from email payload...")

            for attachment in attachments_raw:
                file_name      = attachment.get("name", "unknown_file")
                content_bytes  = attachment.get("contentBytes", "")   # Base64 string from Power Automate
                content_type   = attachment.get("contentType", "application/octet-stream")
                is_inline      = attachment.get("isInline", False)

                # Skip inline images (logos, signatures etc.)
                if is_inline:
                    logging.info(f"[ATTACHMENT] Skipping inline attachment: {file_name}")
                    continue

                # Decode Base64 → raw bytes
                try:
                    file_bytes = base64.b64decode(content_bytes)
                except Exception as e:
                    logging.warning(f"[ATTACHMENT] Could not decode {file_name}: {str(e)}")
                    continue

                # Upload decoded file to Blob Storage under case_id folder
                blob_path   = f"{case_id}/{file_name}"
                blob_client = container_client.get_blob_client(blob_path)
                blob_client.upload_blob(file_bytes, overwrite=True)
                logging.info(f"[BLOB UPLOAD] Stored -> {blob_path}")

                attachments.append({
                    "fileName":  file_name,
                    "fileBytes": file_bytes
                })
        else:
            # No attachments in payload — scan Blob for existing files under case_id
            logging.info(f"[BLOB SCAN] No attachments in payload. Scanning blob for prefix '{case_id}/'")
            blob_list = list(container_client.list_blobs(name_starts_with=f"{case_id}/"))
            logging.info(f"[BLOB COUNT] Found {len(blob_list)} existing blob(s)")

            for blob in blob_list:
                logging.info(f"Loading existing blob: {blob.name}")
                blob_client = container_client.get_blob_client(blob.name)
                file_bytes  = bytes(blob_client.download_blob().readall())
                attachments.append({
                    "fileName":  blob.name.split("/")[-1],
                    "fileBytes": file_bytes
                })

        if not attachments:
            logging.warning(f"No attachments found for case {case_id}")
            return func.HttpResponse(
                json.dumps({"error": f"No attachments found for case {case_id}"}),
                mimetype="application/json",
                status_code=404
            )

        logging.info(f"Total attachments to process: {len(attachments)}")

        # ---------------------------------------------------------------
        # STEP 6: Build api_payload using email fields from the payload
        # ---------------------------------------------------------------
        api_payload = {
            "caseId":   case_id,
            "caseType": "Application Fraud",
            "fraudCategory": "Amount Fraud",
            "priority": "High",
            "email": {
                "from":        email_from,          # ← from Power Automate JSON
                "subject":     email_subject,       # ← from Power Automate JSON
                "description": email_body,          # ← full email body from Power Automate JSON
                "receivedOn":  email_received_on    # ← from Power Automate JSON
            },
            "attachments": [{"fileName": a["fileName"]} for a in attachments]
        }

        email_description = api_payload["email"]["description"]

        # ---------------------------------------------------------------
        # STEP 7: OCR processing (unchanged)
        # ---------------------------------------------------------------
        def analyze_files(file_bytes):
            try:
                poller = doc_int_client.begin_analyze_document(
                    model_id="prebuilt-layout",
                    body=file_bytes
                )
                result = poller.result()
                lines  = []
                for page in result.pages:
                    for line in page.lines:
                        lines.append(line.content)
                return "\n".join(lines)
            except Exception as e:
                logging.error(f"Error analyzing document: {str(e)}")
                return ""

        logging.info("Starting OCR processing...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(
                analyze_files,
                [a["fileBytes"] for a in attachments]
            ))

        ocr_text = "\n".join(results)
        logging.info(f"OCR completed. Extracted {len(ocr_text)} characters")

        # ---------------------------------------------------------------
        # STEP 8: First GPT call — Entity extraction (unchanged)
        # ---------------------------------------------------------------
        logging.info("Calling GPT for entity extraction...")
        prompt = f"""Extract ONLY the following entities. Return STRICT JSON.
                    Applicant Name
                    Customer ID
                    Branch Code
                    Requested Amount
                    Sanctioned Amount

                    EMAIL:
                    {email_description}

                    DOCUMENT TEXT:
                    {ocr_text}
                    """

        response = aoai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract structured fraud investigation entities."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0,
            max_tokens=400
        )

        raw_output = response.choices[0].message.content
        cleaned    = raw_output.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        try:
            cleaned_entities = json.loads(cleaned)
            logging.info(f"Entities extracted: {json.dumps(cleaned_entities)}")
        except Exception as e:
            logging.error(f"Invalid JSON from GPT: {cleaned}")
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON returned by model", "raw_output": cleaned}),
                mimetype="application/json",
                status_code=500
            )

        # ---------------------------------------------------------------
        # STEP 9: Second GPT call — Summary generation (unchanged)
        # ---------------------------------------------------------------
        logging.info("Calling GPT for summary generation...")
        final_prompt = f"""You are a senior bank fraud investigation officer.
                Using ONLY the data below, generate a clear investigation summary.
                CASE ID: {case_id} 
                EXTRACTED ENTITIES: {json.dumps(cleaned_entities, indent=2)}
                OCR DOCUMENT TEXT: {ocr_text[:2000]}
                
                Return STRICT JSON with:
                - case_id
                - summary (3-4 sentences)
                - key_findings (bullet list)
                - risk_level (LOW / MEDIUM / HIGH)
                - recommended_action (single sentence) 
                No markdown. No explanations. 
                """

        final_response = aoai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You produce fraud investigation summaries."},
                {"role": "user",   "content": final_prompt}
            ],
            temperature=0.2,
            max_tokens=500
        )

        final_raw_output = final_response.choices[0].message.content.strip()

        if final_raw_output.startswith("```"):
            final_raw_output = final_raw_output.replace("```json", "").replace("```", "").strip()

        summary_json = json.loads(final_raw_output)
        logging.info(f"Summary generated: {json.dumps(summary_json)}")

        # ---------------------------------------------------------------
        # STEP 10: Store in Cosmos DB (unchanged)
        # ---------------------------------------------------------------
        logging.info("Storing results in Cosmos DB...")
        doc_id   = f"{case_id}-{random.randint(10, 99)}"
        document = {
            "id":                 doc_id,
            "case_id":            case_id,
            "timestamp":          datetime.utcnow().isoformat(),
            "email_from":         email_from,
            "email_subject":      email_subject,
            "email_received_on":  email_received_on,
            "ocr_text":           ocr_text,
            "extracted_entities": cleaned_entities,
            "summary_result":     summary_json
        }

        container.upsert_item(document)
        logging.info(f"Document stored with id: {doc_id}")

        # ---------------------------------------------------------------
        # STEP 11: Return final response
        # ---------------------------------------------------------------
        return func.HttpResponse(
            json.dumps(summary_json, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error":   "Internal server error",
                "message": str(e)
            }),
            mimetype="application/json",
            status_code=500
        )