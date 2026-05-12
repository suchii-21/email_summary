import azure.functions as func
import logging, json, base64, os
from vector_search import get_top_chunk
# from pii_redaction import PIIREDACTION
from services.config import Config
from services.pii_service import PIIService
from services.content_safety import ContentSafetyService

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

def append_to_txt(email_session_id, content):
    """
    Store the emailbody + subject in the blob folder
    
    """
    tmp_dir = "/tmp/email_sessions"
    os.makedirs(tmp_dir, exist_ok=True)

    file_name = f"{email_session_id}_email_body_file.txt"
    file_path = os.path.join(tmp_dir, file_name)

    with open(file_path, "a", encoding="utf-8") as f:
 
            f.write(content+ "\n")
    logging.info(f"[EMAIL BODY] Appended content to '{file_path}'")

    return file_path

#append all logs to the 
def append_all_logs(email_session_id,content):
    """
    Append all logs to the txt file 
    """

    tmp_dir ="/tmp/email_sessions"
    os.makedirs(tmp_dir, exist_ok=True)

    file_name = f"{email_session_id}_all_logs.txt"
    file_path = os.path.join(tmp_dir, file_name)

    with open(file_path, "a", encoding="utf-8") as f:
 
            f.write(content+ "\n")
    logging.info(f"[EMAIL BODY] Appended content to '{file_path}'")

    return file_path

def run_content_safety(content_safety_service, text):
    result = content_safety_service.analyze(text)
    if not result["allowed"]:
        return func.HttpResponse(
            json.dumps({
                "error": "Your request cannot be processed due to policy restrictions."
            }),
            status_code=400,
            mimetype="application/json"
        )
    return None


@app.route(route="email_summary")
def email_summary(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    #import the necessary modules
    from blob_operations import BlobAttachmentHandler

    blob_clss = BlobAttachmentHandler()

    try:
        from ai_initializtion import AIInitializtion
        ai_class = AIInitializtion()
    except Exception as e:
        logging.error(f'Module error : {e}')


    # try:
    #     from cosmos_logging import CosmosLogs
    #     cosmos_class = CosmosLogs()
    # except Exception as e:
    #     logging.error(f'Module error : {e}')

    try:
        try:
            email_payload = req.get_json()
            logging.warning(f'Initial payload type: {type(email_payload)}')
            # cosmos_class.upsert_log_entries(log_msg=email_payload,
            #                                 status="sucess",
            #                                 session_id=email_payload.get("UID", ""),
            #                                 )

        except ValueError:
            # cosmos_class.upsert_log_entries(log_msg="Value Error",
            #                                 status="Failed")
            return func.HttpResponse(
                json.dumps({"error": "Invalid or missing JSON body"}),
                mimetype="application/json",
                status_code=400
            )


        # Validating the fields 
        required_fields = ["UID"]
        missing_fields = [f for f in required_fields if not email_payload.get(f)]
        if missing_fields:
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields in payload: {missing_fields}"}),
                mimetype="application/json",
                status_code=400
            )
        #if fields are missing set it to an empty string
        email_payload.setdefault("Subject", "")
        email_payload.setdefault("Body", "")
        email_payload.setdefault("Attachments", [])

        #extract the value from the json input
        email_session_id  = email_payload.get("UID", "")
        email_subject  = email_payload.get("Subject", "")
        email_body_raw        = email_payload.get("Body", "")           
        attachments_raw   = email_payload.get("Attachments", [])
        
        email_body = email_subject + "\n\n" + email_body_raw
        logging.warning(f'complete email body is : {email_body}')

        # Deseralizing to   python object
        if isinstance(attachments_raw, str):
            try:
                attachments = json.loads(attachments_raw)
            except json.JSONDecodeError:
                logging.error("Attachments JSON parsing failed")
                attachments = []
        else:
            attachments = attachments_raw    

        logging.info(f"Email session id  : {email_session_id}")

        #store the email subject +  body in the blob
        file_path = append_to_txt(email_session_id,email_body)
        
        append_all_logs(email_session_id,f'email_pay load : {email_payload}')

        try:
            #appload the evidence and the email body + subject to blob
            blob_result =  blob_clss.uploading_attachments_to_blob(email_session_id,
                                                                              attachments)
            
            #get extracted contents from the evidence attached
            extracted_contents = blob_result.get("extracted_contents", {})


            blob_clss.upload_email_body(file_path, email_session_id)
            append_all_logs(email_session_id,f'extracted_content is : {extracted_contents}')
 
            if not extracted_contents:
                logging.warning(f"[SESSION {email_session_id}] No content extracted from any attachment.")

            #concatenate both body and subject

            combined_content_parts = []

            for file_name, content in extracted_contents.items():
                if content:
                    combined_content_parts.append(f"[ATTACHMENT: {file_name}]\n{content}")
 
            combined_content_docs = "\n\n---\n\n".join(combined_content_parts)
        
            combined_content =  f'email body and subject is : {email_body}, and the extracted content from the attachment is : {combined_content_docs}'
            
 
            logging.info(
                f"[SESSION {email_session_id}] Sending combined content to AI. "
                f"Files: {list(extracted_contents.keys())} | "
                f"Total chars: {len(combined_content)}"
            )


            #Check if the email body and subject is safe to test 

            try:
                config = Config()
                content_safety = ContentSafetyService(config)
                pii_service = PIIService(config)

                safety_error = run_content_safety(content_safety, combined_content)
                if safety_error:
                    return safety_error
                

                #redact the PII present in the payload recieved 
                if isinstance(combined_content,list):
                    redacted_chunks, registry = pii_service.mask_chunks(combined_content)
                else:
                    redacted_chunks, registry = pii_service.mask_chunks([combined_content])
            
            except Exception as e:
                logging.error(f'error while fetching the response from ai due to : {e}')
                return func.HttpResponse(json.dumps({"message": "Error while getting the response"}),
                                        status_code = 500,
                                        mimetype="application/json")


            try:


                #get ai response  
                get_ai_response = ai_class.get_extraction(email_session_id,redacted_chunks )
                logging.warning('recived ai response')
                logging.warning(f'trying to restore the pii')

                #remap the redacted values
                final_response = pii_service.restore_pii(get_ai_response,registry)


                #check the safety for the AI generated response
                safety_error = run_content_safety(content_safety, final_response)
                if safety_error:
                    return safety_error

                logging.warning(f'final_response after redaction is : {final_response}')


                #get similar use cases from the index

                try:
                    vclss = get_top_chunk()
                    logging.warning(f'sending combined content to the vector : {combined_content[:50]}')
                    result = vclss.retriveal_of_top_chunk( combined_content)
                    logging.warning(f'got the top chunks')


                    # check content safety for the retrived chunks 
                    safety_error = run_content_safety(content_safety, result)
                    if safety_error:
                        return safety_error

                    #redact the info before sending to AI

                    #redact PII from the retrieved chunks
                    if isinstance(result,list):
                        logging.warning(f'list')
                        redacted_chunks, registry = pii_service.mask_chunks(result)
                    else:
                        logging.warning(f'top chunks are not a list')
                        redacted_chunks, registry = pii_service.mask_chunks([result])
                    logging.warning(f'redacted chunks are: {redacted_chunks}')

                    

                    #get the nature of fraud recommendation
                    get_nature_of_fraud_redacted = ai_class.get_fraud_type( final_response['description'],email_session_id,redacted_chunks) # type: ignore
                   
                   # remap the PII to the AI response
                    get_nature_of_fraud_dict = pii_service.restore_pii(get_nature_of_fraud_redacted, registry)

                    #check content safety for generated response
                    safety_error = run_content_safety(content_safety, result)
                    if safety_error:
                        return safety_error

                    final_response['nature_of_fraud'] = get_nature_of_fraud_dict.get ('nature_of_fraud', '') # type: ignore #type : ignore
                    
                    logging.warning(f'get nature of fraud is : {final_response["nature_of_fraud"]}')#type:ignore

                    

                except Exception as e:
                    logging.warning(f'Failed to retrive the top chunks, sending an empty string : {e}')
                    get_ai_response['nature_of_fraud']  = ''
                
                #appending all the logs to the blob
                file_path =append_all_logs(email_session_id, f'AI  response is : {get_ai_response}')
                blob_clss.upload_email_body(file_path, email_session_id)
                return func.HttpResponse( json.dumps(final_response),
                                        mimetype="application/json",
                                        status_code=200)
            except Exception as e:
                logging.error(f'Failed to get the response')
                return func.HttpResponse(
                json.dumps({
                    "error":   "Internal server error",
                    "message": str(e)
                }),
                mimetype="application/json",
                status_code=500
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