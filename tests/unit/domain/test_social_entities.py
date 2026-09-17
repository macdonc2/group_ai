"""Unit tests for social graph entities (Person, Pet, Location, etc.)."""

import pytest
from datetime import datetime

from agent_system.domain.entities.social import (
    Contradiction,
    Expertise,
    Location,
    Pattern,
    Person,
    Pet,
    Preference,
    Thread,
)
from agent_system.domain.value_objects.knowledge import (
    ExpertiseLevel,
    LocationType,
    PatternType,
    PersonRelationType,
)


class TestPerson:
    """Tests for Person entity."""
    
    def test_create_person(self):
        """Test creating a Person entity."""
        person = Person.create(
            name="John Doe",
            relationship_type=PersonRelationType.FRIEND,
            aliases=["Johnny", "JD"],
            context_notes="Met at work",
        )
        
        assert person.name == "John Doe"
        assert person.relationship_type == PersonRelationType.FRIEND
        assert "Johnny" in person.aliases
        assert "JD" in person.aliases
        assert person.context_notes == "Met at work"
        assert person.mention_count == 1
    
    def test_update_mention(self):
        """Test updating mention timestamp and count."""
        person = Person.create(name="Jane")
        assert person.mention_count == 1
        
        updated = person.update_mention()
        assert updated.mention_count == 2
        assert updated.last_mentioned > person.first_mentioned
    
    def test_add_alias(self):
        """Test adding an alias."""
        person = Person.create(name="Robert")
        assert len(person.aliases) == 0
        
        person = person.add_alias("Bob")
        assert "Bob" in person.aliases
        
        # Adding same alias (case-insensitive) shouldn't duplicate
        person = person.add_alias("bob")
        assert len(person.aliases) == 1
    
    def test_matches_name_or_alias(self):
        """Test name/alias matching."""
        person = Person.create(name="Elizabeth", aliases=["Liz", "Beth"])
        
        assert person.matches_name_or_alias("Elizabeth")
        assert person.matches_name_or_alias("elizabeth")  # Case-insensitive
        assert person.matches_name_or_alias("Liz")
        assert person.matches_name_or_alias("Beth")
        assert not person.matches_name_or_alias("Lisa")


class TestPet:
    """Tests for Pet entity."""
    
    def test_create_pet(self):
        """Test creating a Pet entity."""
        pet = Pet.create(
            name="Bo",
            species="dog",
            breed="Golden Retriever",
            aliases=["Bo Boy"],
        )
        
        assert pet.name == "Bo"
        assert pet.species == "dog"
        assert pet.breed == "Golden Retriever"
        assert "Bo Boy" in pet.aliases
    
    def test_add_trait(self):
        """Test adding personality traits."""
        pet = Pet.create(name="Max", species="dog")
        
        pet = pet.add_trait("playful")
        pet = pet.add_trait("loyal")
        assert "playful" in pet.personality
        assert "loyal" in pet.personality
        
        # No duplicates
        pet = pet.add_trait("Playful")
        assert len(pet.personality) == 2
    
    def test_add_food_preference(self):
        """Test adding food preferences."""
        pet = Pet.create(name="Whiskers", species="cat")
        
        pet = pet.add_food_preference("tuna")
        pet = pet.add_food_preference("chicken")
        
        assert "tuna" in pet.food_preferences
        assert "chicken" in pet.food_preferences


class TestLocation:
    """Tests for Location entity."""
    
    def test_create_location(self):
        """Test creating a Location entity."""
        location = Location.create(
            name="Memorial Park",
            location_type=LocationType.PARK,
            city="Houston",
        )
        
        assert location.name == "Memorial Park"
        assert location.location_type == LocationType.PARK
        assert location.city == "Houston"
    
    def test_add_activity(self):
        """Test adding associated activities."""
        location = Location.create(name="24 Hour Fitness", location_type=LocationType.GYM)
        
        location = location.add_activity("weightlifting")
        location = location.add_activity("cardio")
        
        assert "weightlifting" in location.associated_activities
        assert "cardio" in location.associated_activities
    
    def test_matches_name_or_alias(self):
        """Test location name matching."""
        location = Location.create(
            name="In The Loop Hair Salon",
            aliases=["The Loop", "ITL"],
        )
        
        assert location.matches_name_or_alias("loop")  # Partial match
        assert location.matches_name_or_alias("ITL")
        assert not location.matches_name_or_alias("Cuts")


class TestPattern:
    """Tests for Pattern entity."""
    
    def test_create_pattern(self):
        """Test creating a Pattern entity."""
        pattern = Pattern.create(
            pattern_type=PatternType.WEEKLY_EVENT,
            description="Goes to gym on Saturdays",
            frequency="weekly",
            confidence=0.8,
        )
        
        assert pattern.pattern_type == PatternType.WEEKLY_EVENT
        assert pattern.description == "Goes to gym on Saturdays"
        assert pattern.frequency == "weekly"
        assert pattern.confidence == 0.8
    
    def test_record_occurrence(self):
        """Test recording pattern occurrences."""
        pattern = Pattern.create(
            pattern_type=PatternType.DAILY_HABIT,
            description="Morning coffee",
        )
        
        assert pattern.occurrence_count == 0
        
        pattern = pattern.record_occurrence()
        assert pattern.occurrence_count == 1
        assert pattern.last_occurrence is not None


class TestThread:
    """Tests for Thread entity."""
    
    def test_create_thread(self):
        """Test creating a Thread entity."""
        thread = Thread.create(
            name="Project Alpha",
            description="Working on the new feature",
        )
        
        assert thread.name == "Project Alpha"
        assert thread.status == "active"
        assert len(thread.conversation_ids) == 0
    
    def test_add_conversation(self):
        """Test adding conversations to thread."""
        thread = Thread.create(name="Bug Investigation")
        
        thread = thread.add_conversation("conv-1")
        thread = thread.add_conversation("conv-2")
        
        assert len(thread.conversation_ids) == 2
        assert "conv-1" in thread.conversation_ids
        
        # No duplicates
        thread = thread.add_conversation("conv-1")
        assert len(thread.conversation_ids) == 2


class TestExpertise:
    """Tests for Expertise entity."""
    
    def test_create_expertise(self):
        """Test creating an Expertise entity."""
        expertise = Expertise.create(
            topic="Python",
            level=ExpertiseLevel.ADVANCED,
        )
        
        assert expertise.topic == "Python"
        assert expertise.level == ExpertiseLevel.ADVANCED
    
    def test_add_evidence(self):
        """Test adding evidence of expertise."""
        expertise = Expertise.create(topic="Cooking", level=ExpertiseLevel.BEGINNER)
        
        expertise = expertise.add_evidence("Made a simple pasta dish")
        expertise = expertise.add_evidence("Asked about basic techniques")
        
        assert expertise.evidence_count == 2
        assert len(expertise.evidence_snippets) == 2


class TestPreference:
    """Tests for Preference entity."""
    
    def test_create_preference(self):
        """Test creating a Preference entity."""
        pref = Preference.create(
            category="food",
            value="sushi",
            sentiment=0.9,
            subcategory="Japanese",
        )
        
        assert pref.category == "food"
        assert pref.value == "sushi"
        assert pref.sentiment == 0.9
        assert pref.subcategory == "Japanese"
    
    def test_update_mention(self):
        """Test updating preference mentions."""
        pref = Preference.create(category="activities", value="cycling")
        assert pref.mention_count == 1
        
        pref = pref.update_mention("conv-123")
        assert pref.mention_count == 2
        assert "conv-123" in pref.source_conversations


class TestContradiction:
    """Tests for Contradiction entity."""
    
    def test_create_contradiction(self):
        """Test creating a Contradiction entity."""
        contradiction = Contradiction.create(
            entity_type="person",
            entity_name="John",
            attribute="age",
            old_value="30",
            new_value="35",
            severity=0.7,
        )
        
        assert contradiction.entity_name == "John"
        assert contradiction.old_value == "30"
        assert contradiction.new_value == "35"
        assert not contradiction.resolved
    
    def test_resolve_contradiction(self):
        """Test resolving a contradiction."""
        contradiction = Contradiction.create(
            entity_type="pet",
            entity_name="Max",
            attribute="breed",
            old_value="Labrador",
            new_value="Golden Retriever",
        )
        
        resolved = contradiction.resolve("Confirmed as Golden Retriever mix")
        
        assert resolved.resolved
        assert resolved.resolution == "Confirmed as Golden Retriever mix"
        assert resolved.resolved_at is not None


class TestConversationPersona:
    """A conversation remembers the wrestler it was last spoken in."""

    def test_default_is_plain(self):
        from agent_system.domain.entities.conversation import Conversation
        from agent_system.domain.value_objects import UserId

        conv = Conversation.create(user_id=UserId.generate())
        assert conv.persona is None

    def test_with_persona_round_trips_and_clears(self):
        from agent_system.domain.entities.conversation import Conversation
        from agent_system.domain.value_objects import UserId

        conv = Conversation.create(user_id=UserId.generate()).update_metadata(custom_data={"keep": 1})
        themed = conv.with_persona("bret_hart")
        assert themed.persona == "bret_hart" and themed.metadata.custom_data["keep"] == 1
        assert themed.with_persona("bret_hart") is themed  # no-op when unchanged
        assert themed.with_persona(None).persona is None
        assert themed.with_persona("").persona is None
