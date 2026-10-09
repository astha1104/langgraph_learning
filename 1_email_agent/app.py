import uuid

import streamlit as st
from langgraph.types import Command

from agent import final_graph


st.set_page_config(
    page_title="Email Studio",
    page_icon="✉️",
    layout="centered",
)

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(ellipse at 12% 0%, rgba(104, 87, 230, .13), transparent 34rem),
            #f7f8fc;
        color: #182033;
    }
    .stApp h1,
    .stApp h2,
    .stApp h3,
    .stApp p,
    .stApp label,
    .stApp [data-testid="stCaptionContainer"],
    .stApp [data-testid="stMarkdownContainer"] {
        color: #182033;
    }
    .block-container {
        max-width: 850px;
        padding-top: 3rem;
        padding-bottom: 4rem;
    }
    .eyebrow {
        color: #6556c9;
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .12em;
        text-transform: uppercase;
    }
    div[data-testid="stForm"] {
        background: white;
        border: 1px solid #e8e9f1;
        border-radius: 18px;
        padding: 1.35rem;
    }
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea {
        background-color: #fff;
        color: #182033;
        -webkit-text-fill-color: #182033;
        border-color: #c9ccda;
    }
    div[data-baseweb="input"] input::placeholder,
    div[data-baseweb="textarea"] textarea::placeholder {
        color: #626b80;
        -webkit-text-fill-color: #626b80;
        opacity: 1;
    }
    .stApp button[kind="primary"] {
        background-color: #5948bd;
        color: #fff;
    }
    .stApp button[kind="secondary"] {
        background-color: #eef0f7;
        color: #182033;
        border: 1px solid #c9ccda;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<p class="eyebrow">Your writing assistant</p>', unsafe_allow_html=True)
st.title("Email Studio")
st.write("Describe the email you need. Review the draft before anything is sent.")

if "email_thread_id" not in st.session_state:
    st.session_state.email_thread_id = str(uuid.uuid4())
    st.session_state.email_draft = None
    st.session_state.email_awaiting_review = False
    st.session_state.email_response = None

config = {
    "configurable": {"thread_id": st.session_state.email_thread_id}
}


def refresh_workflow_state() -> None:
    snapshot = final_graph.get_state(config)
    st.session_state.email_draft = dict(snapshot.values)
    st.session_state.email_awaiting_review = bool(snapshot.next)
    st.session_state.email_response = (
        None if snapshot.next else snapshot.values.get("response")
    )


with st.form("compose_email"):
    question = st.text_area(
        "What should the email say?",
        placeholder=(
            "For example: Write to Alex at alex@example.com to thank them "
            "for the interview and ask about next steps."
        ),
        height=130,
    )
    start_draft = st.form_submit_button(
        "Create email draft",
        type="primary",
        use_container_width=True,
    )

if start_draft:
    if not question.strip():
        st.error("Describe the email you want to write first.")
    else:
        with st.spinner("Writing your draft..."):
            final_graph.invoke({"question": question.strip()}, config=config)
            refresh_workflow_state()
        st.rerun()

if st.session_state.email_awaiting_review:
    draft = st.session_state.email_draft
    st.subheader("Review your draft")
    st.caption("Edit any field below, or request a rewrite before sending.")

    with st.form("review_email"):
        recipient_email = st.text_input(
            "To",
            value=draft.get("recipient_email", ""),
        )
        subject = st.text_input("Subject", value=draft.get("subject", ""))
        body = st.text_area("Message", value=draft.get("body", ""), height=250)
        feedback = st.text_input(
            "Request a rewrite (optional)",
            placeholder="For example: Make it warmer and keep it shorter.",
        )
        revise, approve = st.columns(2)
        request_revision = revise.form_submit_button(
            "Rewrite draft",
            use_container_width=True,
        )
        approve_and_send = approve.form_submit_button(
            "Approve & send",
            type="primary",
            use_container_width=True,
        )

    if request_revision:
        if not feedback.strip():
            st.error("Add feedback to tell the agent how to revise the draft.")
        else:
            with st.spinner("Revising your draft..."):
                final_graph.invoke(Command(resume=feedback.strip()), config=config)
                refresh_workflow_state()
            st.rerun()

    if approve_and_send:
        if not recipient_email.strip():
            st.error("Enter a recipient email address before sending.")
        elif not subject.strip() or not body.strip():
            st.error("The subject and message must not be empty.")
        else:
            with st.spinner("Sending your email..."):
                final_graph.update_state(
                    config,
                    {
                        "recipient_email": recipient_email.strip(),
                        "subject": subject.strip(),
                        "body": body.strip(),
                    },
                )
                final_graph.invoke(Command(resume="yes"), config=config)
                refresh_workflow_state()
            st.rerun()

if st.session_state.email_response:
    response = st.session_state.email_response
    if response == "Email sent successfully!":
        st.success(response)
    else:
        st.info(response)
