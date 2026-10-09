from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command,interrupt
from pydantic import BaseModel,Field
from typing import Literal,Annotated
from sent_email import send_email

llm=ChatGroq(model="openai/gpt-oss-20b")

class EmailState(BaseModel):
    question:str=""
    mail_reason:str=""
    recipient_name:str=""
    recipient_email:str=""
    subject:str=""
    body:str=""
    feedback:str=""
    feedback_count:int=0 #Max count 3
    response:str=""

class UserDetails(BaseModel):
    mail_reason:str=Field(description="Reason of email,like why user want to sent the email")
    recipient_name:str=Field(description="recipient /reciever name ,if available")
    recipient_email:str=Field(description="recipient /reciever email address")

def retriever_node(state:EmailState)->EmailState:
    llm_for_user_details=llm.with_structured_output(UserDetails)
    userdetails:UserDetails=llm_for_user_details.invoke(
        f"Retrive the user details from this query:{state.question}"
    )

    if not userdetails.mail_reason or not userdetails.recipient_email:
        pass

    state.recipient_name=userdetails.recipient_name
    state.recipient_email=userdetails.recipient_email
    state.mail_reason=userdetails.mail_reason

    return state

### Draft Node
class DraftEmail(BaseModel):
    subject:str=Field(description="Email Subject within 40 words.")
    body:str=Field(description="Email body including proper details,reason,greetings and other.")

def draft_node(state:EmailState)->EmailState:
    "Draft a Email"
    draft_email_llm=llm.with_structured_output(DraftEmail)

    prompt=f"""
        write a email with details:
        TO:{state.recipient_name}
        Request:{state.mail_reason}

        please write the proper email body and subject.Without extra words.
        Mail body max size will be 200 words.
    """

    if state.feedback:
        prompt=f"""Revise this email based on feedback below.
        Current email:
            subject:{state.subject}
            body:{state.body}

        feedback:{state.feedback}
        please write the proper email body and subject.Without extra words and improve the email based on the feedback.
        Mail body max size will be 200 words.
        """
    draftemail:DraftEmail=draft_email_llm.invoke(prompt)
    state.subject=draftemail.subject
    state.body=draftemail.body

    return state

def review_node(state:EmailState)->EmailState:
    print("\n")
    print("-"*50)
    print("Subject: ",state.subject,"\n")
    print("Body:",state.body)
    print("-"*50)

    response=interrupt({
        "message":"You want to approve this email or rewrite this email."
    })

    if response == "yes":
        state.feedback=""
    else:
        state.feedback=response
        state.feedback_count=state.feedback_count+1

    return state

def router(state:EmailState)->Literal["draft","send","cancel"]:
    if not state.feedback or state.feedback.strip()=="":
        return "send"

    if state.feedback_count >2:
        return "cancel"
    
    return "draft"

def cancel_node(state:EmailState)->EmailState:
    state.response="Email was not sent because you reached the revision limit."
    return state

def send_node(state:EmailState)->EmailState:
    "send final email"
    res = send_email(state.recipient_email, state.subject, state.body)
    state.response = res
    return state

graph=StateGraph(EmailState)

graph.add_node("retriver",retriever_node)
graph.add_node("draft",draft_node)
graph.add_node("review_node",review_node)
graph.add_node("send",send_node)
graph.add_node("cancel",cancel_node)

graph.add_edge(START,"retriver")
graph.add_edge("retriver","draft")
graph.add_edge("draft","review_node")
graph.add_conditional_edges("review_node",router)
graph.add_edge("send",END)
graph.add_edge("cancel",END)

final_graph=graph.compile(checkpointer=InMemorySaver())

