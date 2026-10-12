from sqlalchemy import create_engine,Column,Integer,Float,Boolean,DateTime,String
from sqlalchemy.orm import DeclarativeBase,Session
from datetime import datetime
from db import movies

engine=create_engine("sqlite:///./cinema.db",echo=False)

class Base(DeclarativeBase):
    pass

class Movies(Base):
    __tablename__="movies"

    id=Column(Integer,primary_key=True,autoincrement=True)
    title=Column(String,nullable=False)
    genre=Column(String)
    show_time=Column(String)
    price=Column(Float)
    total_seats=Column(Integer,default=0)
    booked_seats=Column(Integer,default=0)

    @property
    def available(self) -> int:
        return self.total_seats - self.booked_seats   

class Booking(Base):
    __tablename__="booking"

    id=Column(Integer,primary_key=True,autoincrement=True)
    movie_id=Column(Integer)
    customer_name=Column(String)
    seats=Column(Integer)
    total_amount=Column(Float)
    status=Column(String,default="confirmed")
    booked_at=Column(DateTime,default=datetime.now)

def create_table():
    Base.metadata.create_all(engine)

def seed_movies():
    with Session(engine) as db:
        if db.query(Movies).count()>0:
            return
      
        movieObjects=[]
        for movie in movies:
            movieObjects.append(
                Movies(
                    title=movie["title"],
                    genre=movie["genre"],
                    show_time=movie["show_time"],
                    price=movie["price"],
                    total_seats=movie["total_seats"]
                )
            )

        db.add_all(movieObjects)
        db.commit()
        print("All movies created!!")



