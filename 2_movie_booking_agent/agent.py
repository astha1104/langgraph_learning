from models import engine, seed_movies, create_table, Movies, Booking
from sqlalchemy.orm import Session
from dotenv import load_dotenv
load_dotenv()
import json

#### Import all the packages
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional

create_table()
seed_movies()

class ClassifiedIntent(BaseModel):
    """Classify a movie-booking message and extract only the details the user stated."""

    intent: Literal[
        "list_movies", "movie_details", "book_ticket",
        "cancel_booking", "check_booking", "return_tickets", "general"
    ] = Field(description="The single action the user wants to perform right now.")

    movie_id: Optional[int] = Field(
        default=None,
        description="Numeric ID of a MOVIE, e.g. 'movie 3' -> 3. Never a booking number.",
    )
    movie_title: Optional[str] = Field(
        default=None,
        description="Movie name as the user wrote it, e.g. 'tickets for Inception' -> 'Inception'.",
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="Name of the person the booking is for, e.g. 'for Alice' -> 'Alice'. Never invent one.",
    )
    seats: Optional[int] = Field(
        default=None,
        description="Number of seats/tickets as an integer, e.g. 'two tickets' -> 2.",
    )
    booking_id: Optional[int] = Field(
        default=None,
        description="Numeric ID of an existing BOOKING, e.g. 'booking #4' -> 4. Never a movie number.",
    )


class CinemaState(BaseModel):
    user_message:  str = ""
    intent:        str = ""
    movie_id:      Optional[int] = None
    movie_title:   Optional[str] = None
    customer_name: Optional[str] = None
    seats:         Optional[int] = None
    booking_id:    Optional[int] = None
    total_amount:  float = 0
    result:        str    = ""
    data: dict = {}

llm = ChatGroq(model="openai/gpt-oss-20b")
intent_llm = llm.with_structured_output(ClassifiedIntent)


#### Intent prompt
CLASSIFIER_SYSTEM_PROMPT = """You are the intent classifier for CinemaBot, a movie ticket booking assistant.
Read the user's message, choose exactly ONE intent, and extract only the details the user actually stated.

INTENTS
- list_movies    : wants to see what is showing (all movies, schedule, what's available)
- movie_details  : asks about ONE specific movie (price, show time, genre, seats left)
- book_ticket    : wants to book, buy, or reserve seats for a movie
- cancel_booking : wants to cancel an existing booking
- check_booking  : wants the status or details of an existing booking
- return_tickets : explicitly wants to RETURN tickets from an existing booking (different from cancel)
- general        : greetings, thanks, help, or anything that fits none of the above

EXTRACTION RULES
1. If a detail is not in the message, leave it null. Never guess or invent values.
2. A number that refers to a movie ("movie 3") goes in movie_id. A number that refers to a
   booking ("booking 4", "booking #4") goes in booking_id. Never put the same number in both.
3. movie_title is only the film's name, without words like "movie" or "tickets".
4. customer_name is the person the booking is for ("for Alice", "I'm Raj", "my name is Priya").
5. seats must be an integer. Convert number words to digits ("two" -> 2).
6. If the message mentions several actions, pick the main one the user wants done now.

EXAMPLES
"what movies are playing tonight?"          -> list_movies
"how much is a ticket for Interstellar?"    -> movie_details, movie_title="Interstellar"
"book 2 tickets for Inception for Alice"    -> book_ticket, movie_title="Inception", seats=2, customer_name="Alice"
"I want three seats for movie 4"            -> book_ticket, movie_id=4, seats=3
"cancel booking 7"                          -> cancel_booking, booking_id=7
"is booking #3 confirmed?"                  -> check_booking, booking_id=3
"I'd like to return my tickets, booking 5"  -> return_tickets, booking_id=5
"hi, what can you do?"                      -> general
"""


### Classifier Node
def classifier_node(state:CinemaState):
    query = state.user_message
    intent:ClassifiedIntent = intent_llm.invoke([
        {"role":"system", "content": CLASSIFIER_SYSTEM_PROMPT}, 
        {"role":"user", "content": query}, 
        ])  
      
    state.intent = intent.intent
    state.movie_id = intent.movie_id
    state.movie_title  = intent.movie_title
    state.customer_name  = intent.customer_name
    state.seats  = intent.seats
    state.booking_id  = intent.booking_id
    
    return state


def list_movies_node(state:CinemaState) -> dict:
    with Session(engine) as db:
        movies = db.query(Movies).all()
        all_movies = []
        for m in movies:
            all_movies.append(
                {
                    "id":              m.id,
                    "title":           m.title,
                    "genre":           m.genre,
                    "show_time":       m.show_time,
                    "price_per_seat":  m.price,
                    "available_seats": m.available,
                    "total_seats":     m.total_seats,
                }
            )
            
        return {"data": {"all_movies": all_movies} }
        

def movies_detail_node(state:CinemaState) -> dict:
    movie = None
    with Session(engine) as db:
        if state.movie_id:
            movie = db.get(Movies, state.movie_id)
        elif state.movie_title:
            movie = db.query(Movies).filter(Movies.title.ilike(f"%{state.movie_title}%")).first()
    
    if not movie:
        return {"data": {"error": "Please provide correct movie id or title, and try to list the movies list first"}}
    
    
    movie = {
                "id":              movie.id,
                "title":           movie.title,
                "genre":           movie.genre,
                "show_time":       movie.show_time,
                "price_per_seat":  movie.price,
                "available_seats": movie.available,
                "total_seats":     movie.total_seats,
            }
    
    return {"data": { "movie": movie } }
        
            
def book_info_node(state:CinemaState) -> dict:
    movie_id = None
    if state.movie_id:
        movie_id = state.movie_id
        
    if not state.movie_id and state.movie_title:
        with Session(engine) as db:
            movie = db.query(Movies).filter(Movies.title.ilike(f"%{state.movie_title}%")).first()
            if movie:
                movie_id = movie.id
                
    
    missing = []
    if not movie_id: missing.append("Movie Id or title")
    if not state.customer_name: missing.append("Customer Name")
    if not state.seats: missing.append("Required Seats for booking")
    
    if len(missing) > 0:
        return {"data": {"error": f"Please provide these missing details: {', '.join(missing)}"}}
    
    
    with Session(engine) as db:
        movie = db.get(Movies, movie_id)
        if not movie:
            return {"data": {"error": f"Please provide correct movie_id, {movie_id}"}}
            
        if movie.available < state.seats:
            return {"data": {"error": f"We have only {movie.available} seats, so we can not book {state.seats} seats"}}
        
        return {
            "movie_id":     movie_id,
            "movie_title":  movie.title,
            "total_amount": state.seats * movie.price,
            "data": {}
        }
        

def confirm_booking_node(state:CinemaState) -> dict:
    response = interrupt({
        "message": "Confirm Your Booking ? Yes / No"
    })
    
    if response.lower().strip() != "yes":
        return {"data": {"error": "Movie Booking Canceled by the user"}}
    
    with Session(engine) as db:
        movie = db.get(Movies, state.movie_id)
        booking = Booking(
            movie_id = state.movie_id,
            customer_name = state.customer_name,
            seats = state.seats,
            total_amount = state.seats * movie.price
        )
        
        movie.total_seats = movie.total_seats - state.seats
        db.add(booking)
        db.commit()
        db.refresh(booking)

        return {"data": {
            "status":     "confirmed",
            "booking_id": booking.id,
            "movie":      movie.title,
            "show_time":  movie.show_time,
            "customer":   state.customer_name,
            "seats":      state.seats,
            "total_paid": booking.total_amount,
        }}


def check_booking_node(state: CinemaState) -> dict:
    if not state.booking_id:
        return {"data": {"error": "Booking Id required..."}}
    
    with Session(engine) as db:
        booking = db.get(Booking, state.booking_id)
        if not booking:
            return {"data": {"error": "Booking Id not found Please provide the correct booking Id..."}}
        
        movie = db.get(Movies, booking.movie_id)

        return {"data": {
            "movie_name": movie.title,
            "customer_name" : booking.customer_name,
            "total_amoutn" : booking.total_amount,
            "seats": booking.seats,
            "show_time": movie.show_time,
            "status": booking.status,
        }}
        
        
def cancel_booking_node(state: CinemaState) -> dict:
    if not state.booking_id:
        return {"data": {"error": "Booking Id required..."}}
    
    with Session(engine) as db:
        booking = db.get(Booking, state.booking_id)
        if not booking:
            return {"data": {"error": "Booking Id not found Please provide the correct booking Id..."}}
        
        if booking.status != "confirmed":
            return {"data": {"error": f"Booking already canceled for booking id {booking.id}"}}
        
        movie = db.get(Movies, booking.movie_id)
        
        booking.status = "Canceled"
        movie.booked_seats = movie.booked_seats + booking.seats
        
        db.commit()
        
        return {"data": {
            "message": f"Movie Ticked canceled for '{movie.title}', and {booking.total_amount} will be refunded within 3 working days"
        }}



#### Define Router Node
def route_by_intent(state:CinemaState) -> Literal["list_movies", "movie_details", "book_ticket", "check_booking", "cancel_booking"]:
    return state.intent


def router_after_book_info(state:CinemaState) -> Literal["respond_node", "confirm_booking"]:
    if state.data.get("error", None):
        return "respond_node"
    return "confirm_booking"
           
           
def respond_node(state:CinemaState) -> CinemaState:
    data = state.data
    prompt = f"""You are CinemaBot, a friendly and helpful movie ticket booking assistant.
    The user said: "{state.user_message}"
    The system performed action: {state.intent}
    Here is the raw result data: {json.dumps(data, indent=2)}

    Instructions:
    - If data has an "error" key, explain the problem clearly and suggest what the user can do next.
    - If it is a movie list, show each movie on its own line with ID, title, genre, showtime, price, and available seats.
    - If it is a booking confirmation, show a clear summary: movie, name, seats, total paid, and booking ID.
    - If it is a cancellation or return, mention the refund amount. For returns, note that 20% is deducted.
    - If it is a general query, answer helpfully and suggest 2-3 things the user can do.
    - Use emojis where natural. Keep the response concise and easy to read."""
    
    res = llm.invoke(prompt)
    
    state.result = res.content
    return state
    

graph = StateGraph(CinemaState)

graph.add_node("classifier", classifier_node)
graph.add_node("list_movies", list_movies_node)
graph.add_node("movie_details", movies_detail_node)
graph.add_node("book_ticket", book_info_node)
graph.add_node("confirm_booking", confirm_booking_node)
graph.add_node("respond_node", respond_node)
graph.add_node("check_booking", check_booking_node)
graph.add_node("cancel_booking", cancel_booking_node)

graph.add_edge(START, "classifier")
graph.add_conditional_edges("classifier", route_by_intent)

graph.add_edge("list_movies", "respond_node")
graph.add_edge("movie_details", "respond_node")
graph.add_edge("movie_details", "respond_node")
graph.add_edge("cancel_booking", "respond_node")
graph.add_edge("check_booking", "respond_node")

graph.add_conditional_edges("book_ticket", router_after_book_info)
graph.add_edge("confirm_booking", "respond_node")

graph.add_edge("respond_node", END)


final_graph = graph.compile(checkpointer=InMemorySaver())

# res = final_graph.invoke(
#     {"user_message": "Status of Movie 8, and move name 'RRR'"}, 
#     {"configurable" :  {"thread_id" :"1"}}
#     )

# print(res)








