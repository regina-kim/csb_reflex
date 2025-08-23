import os
from typing import Any, TypedDict
import reflex as rx
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import pymongo
from dotenv import load_dotenv

load_dotenv() # Loads environment variables from the .env file.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "csb_db")

# Checking if the API key is set properly
if not os.getenv("OPENAI_API_KEY"):
    raise Exception("Please set OPENAI_API_KEY environment variable.")

# Define global MongoDB Client&Database.
try:
    mongo_client = pymongo.MongoClient(MONGO_URI)
    mongo_db = mongo_client[DB_NAME]
    print("Successfully connected to MongoDB.")
except pymongo.errors.ConnectionFailure as e:
    print(f"Failed to connect to MongoDB: {e}")
    # mongo_db = None
    sys.exit(1) # Terminate the app if MongoDB connection fails

class QA(TypedDict):
    """A question and answer pair."""

    question: str
    answer: str

# MongoDB document structure for a single chat.
# Note: In Python, you can use a regular dict as well.
# This is for clarity.
class ChatDocument(TypedDict):
    chat_name: str
    history: list[QA]

class State(rx.State):
    """The app state."""

    # A dict from the chat name to the list of questions and answers.
    # _chats: dict[str, list[QA]] = {
    #     "Intros": [],
    # }
    # Remove the in-memory dictionary.

    # The current chat name.
    current_chat = "Intros"

    # Whether we are processing the question.
    processing: bool = False

    # Whether the new chat modal is open.
    is_modal_open: bool = False

    _history: list[QA] = []  # <--- 이 변수를 추가하세요.

    # 🌟 이 부분을 추가하세요.
    def init(self):
        """Called when the state is initialized."""
        if mongo_db:
            # Check if the "Intros" chat exists. If not, create it.
            if mongo_db.chats.count_documents({"chat_name": "Intros"}) == 0:
                mongo_db.chats.insert_one({"chat_name": "Intros", "history": []})
                print("Created initial 'Intros' chat.")
            
            # Set the current chat to 'Intros' or the first available chat.
            first_chat = mongo_db.chats.find_one({})
            if first_chat:
                self.current_chat = first_chat.get("chat_name")
            else:
                self.current_chat = "Intros" # Fallback if DB is empty

    @rx.var
    def chat_titles(self) -> list[str]:
        """Get the list of chat titles from the database."""
        if mongo_db is None:
            return ["Database Not Connected"]
        
        # Find all documents in the "chats" collection and get their names.
        return [doc["chat_name"] for doc in mongo_db.chats.find({}, {"chat_name": 1})]

    @rx.var
    def selected_chat(self) -> list[QA]:
        """Get the list of questions and answers for the current chat from the database."""
        if mongo_db is None:
            return [QA(question="Database connection failed.", answer="Please check your MongoDB connection.")]

        doc = mongo_db.chats.find_one({"chat_name": self.current_chat})
        # DB에서 가져온 데이터를 _history 변수에 저장
        self._history = doc.get("history", []) if doc else []
        # 그리고 이 변수를 반환하여 UI가 갱신되도록 합니다.
        return self._history

    @rx.event
    def create_chat(self, form_data: dict[str, Any]):
        """Create a new chat in the database."""
        if mongo_db is None:
            return
            
        new_chat_name = form_data["new_chat_name"]
        
        # Check if a chat with the same name already exists.
        if mongo_db.chats.find_one({"chat_name": new_chat_name}):
            print(f"Chat with name '{new_chat_name}' already exists.")
            return

        # Insert a new document with an empty history.
        mongo_db.chats.insert_one({"chat_name": new_chat_name, "history": []})
        self.current_chat = new_chat_name
        self.is_modal_open = False

    @rx.event
    def delete_chat(self, chat_name: str):
        """Delete a chat from the database."""
        if mongo_db is None or chat_name == "Intros":
            # Prevent deleting the default chat
            return
            
        # Delete the document from the "chats" collection.
        mongo_db.chats.delete_one({"chat_name": chat_name})
        
        # Set the current chat to the first available chat.
        chat_list = list(self.chat_titles)
        if chat_list:
            self.current_chat = chat_list[0]
        else:
            # If all chats are deleted, create a new "Intros" chat.
            self.create_chat({"new_chat_name": "Intros"})

    @rx.event
    def set_chat(self, chat_name: str):
        """Set the name of the current chat."""
        self.current_chat = chat_name

    @rx.event
    def set_is_modal_open(self, is_open: bool):
        """Set the new chat modal open state.

        Args:
            is_open: Whether the modal is open.
        """
        self.is_modal_open = is_open

    @rx.event
    def set_new_chat_name(self, new_chat_name: str):
        """Set the name of the new chat."""
        # This function might not be needed if the form handles it directly.
        pass

    @rx.event
    async def process_question(self, form_data: dict[str, Any]):
        """사용자 질문을 처리하고 화면에 즉시 표시합니다."""
        question = form_data["question"]
        if not question or mongo_db is None:
            return

        # 1. 사용자 질문을 MongoDB에 추가하고 즉시 UI를 업데이트합니다.
        #    이 부분이 사용자 메시지를 즉시 보이게 하는 핵심입니다.
        try:
            doc = mongo_db.chats.find_one({"chat_name": self.current_chat})
            if doc:
                history = doc.get("history", [])
                history.append(QA(question=question, answer=""))
                mongo_db.chats.update_one(
                    {"chat_name": self.current_chat},
                    {"$set": {"history": list(history)}}
                )
                self._history = history # 인메모리 변수도 업데이트
                self.processing = True
                yield  # 사용자 메시지가 화면에 즉시 표시되도록 yield
        except Exception as e:
            print(f"Error saving user question: {e}")
            return
            
        # 2. OpenAI 응답을 처리하는 함수를 호출합니다.
        async for value in self.openai_process_question(question):
            yield value

    @rx.event
    async def openai_process_question(self, question: str):
        """Get the response from the API and update the database with the answer."""
        if mongo_db is None:
            self.processing = False
            return
        
        # Build the messages for OpenAI based on the current history.
        # `self._history`는 이미 `process_question`에서 갱신되었습니다.
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": "You are a friendly chatbot named Reflex. Respond in markdown."}
        ]
        for qa in self._history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})

        # Remove the last empty answer placeholder.
        messages = messages[:-1]

        session = OpenAI().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=messages,
            stream=True,
        )

        for item in session:
            if hasattr(item.choices[0].delta, "content"):
                answer_text = item.choices[0].delta.content
                if answer_text is not None:
                    # Append to the last answer in the history list.
                    self._history[-1]["answer"] += answer_text 
                    
                    # Update the database with the streaming answer.
                    mongo_db.chats.update_one(
                        {"chat_name": self.current_chat},
                        {"$set": {"history": list(self._history)}}
                    )
                    yield

        self.processing = False