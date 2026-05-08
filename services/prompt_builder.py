class PromptBuilder:

    @staticmethod
    def build(user_query, contexts):
        context_block = "\n\n".join([
            f"Case {i+1}: {c['chunk']}"
            for i, c in enumerate(contexts)
        ])

        return f'''
- You are an expert in analyzing user queries and relevant context and providing lessons learned and recommendations based on that information. User will provide you with **User Query** and **Relevant Past Cases**. 
- Your task is to analyze the user query in the context of the relevant past cases and provide a structured response containing lessons learned and recommendations. 
- The response should be short, crisp and concise to the point. 
- The response should be strictly in JSON format with two keys: "lessons_learned" and "recommendations". Each key should have a list of strings as its value. 
- Do not include any explanations or additional information outside of the JSON response.
- Lessons learned should include insights that can be drawn from the analysis of current case with respect to the past cases. 
- Recommendations should include actionable suggestions that organization can take on the person involved in the fraud based the complete analysis of current case and past cases only.
- Make sure the response should get generated completely and don't terminate in between and each of the lessons learned and recommendations should not exceed more than 100 words.

Return STRICT JSON:
{{
"lessons_learned": [],
"recommendations": []
}}

Striclty do not include any new line characters and markdown elements in the response JSON

Example for recommendations:
Disciplinary Committee must take an appropriate disciplinary action against the staff/customer <name> (Staff ID/Customer ID: <staff_id/ customer_id>), in line with Employee Conduct & Disciplinary Action Framework, for what ever the nature of the fraud happened in the current case. 

User Query:
{user_query}

Relevant Past Cases:
{context_block}
'''
 