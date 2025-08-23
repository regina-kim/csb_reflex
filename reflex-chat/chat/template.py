import os
from typing import Any, TypedDict, Literal

MIN_TURNS_PER_PHASE = 2
MAX_TURNS_PER_PHASE = 5

Role = Literal["user", "ai_client", "utterance_assistant", "phase_controller"]
CounselingCategory = Literal["academic", "interpersonal", "emotional", "school_life"]
CounselingPhases = ["Exploring", "Choosing", "Guiding", "Terminating"]

class Criteria():
    def __init__(self, criteria: str, score: int, feedback: str):
        self.criteria = criteria
        self.score = score
        self.feedback = feedback

class MITIFeedback():
    def __init__(self):
        self.entries = []

    def store_evaluation(self, criteria: str, score: int, feedback: str):
        entry = Criteria(criteria, score, feedback)
        self.entries.append(entry)
    
    def get_total_feedback(self):
        assert len(self.entries) == 4, "Not all feedback entries are present."
        key_list = [entry.criteria for entry in self.entries]
        return dict(zip(key_list, self.entries))

class Dialogue():
    def __init__(self):
        self.min_turns_per_phase = MIN_TURNS_PER_PHASE
        self.max_turns_per_phase = MAX_TURNS_PER_PHASE
        self.current_phase_idx = 0
        self.turn_count_per_phase = [0, 0, 0, 0]
    
        self.entries = []
        self.is_completed = False
    
    def update_phase(self):
        "Update phase index when moving on to the next phase."
        if self.current_phase_idx < len(CounselingPhases) - 1:
            self.current_phase_idx += 1

        else:
            self.is_completed = True

    def add_utterance(self, role: Role, u_type: str, utterance: str):
        "Add utterances from user or agents."
        assert self.is_completed is False, "Cannot add utterance to completed dialogue."

        # role
        # user, ai_client, utterance_assistant, phase_controller

        # u_type
        # - user: user utterance type selected by user (e.g. restatement, clarification)
        # - others: agent role (ai_client, utterance_assistant, phase_controller)

        # utterance
        # - user: user input
        # - ai_client: AI-generated client utterance
        # - utterance_assistant: AI-generated alternative utterance
        # - phase_controller: CoT reasoning for phase transitions

        self.entries.append({
            "role": role,
            "type": u_type,
            "utterance": utterance,
            "phase": CounselingPhases[self.current_phase_idx]
        })
        # Update turn count for the current phase
        self.turn_count_per_phase[self.current_phase_idx] += 1

        # Move to the next phase if turn limit is reached
        if self.turn_count_per_phase[self.current_phase_idx] >= self.max_turns_per_phase:
            self.update_phase()

    def get_user_conversation(self):
        "Return a conversation between the user and the AI client."
        return [entry for entry in self.entries if entry["role"] == "user" or entry["role"] == "ai_client"]

class ChatDocument(TypedDict):
    
    chat_name: str # chat room name(title)
    # counseling infos
    counseling_category: CounselingCategory 
    seed_concern: str # client's concern seed
    dialogue: Dialogue
    feedback: MITIFeedback