"""Test context-aware command handling."""
import pytest
from datetime import datetime, timedelta

from app.services.command_parser import CommandContext, CommandParser
from app.services.voice_agent import VoiceAgentService, CommandResult


def test_context_expiration():
    """Test that context expires after timeout."""
    context = CommandContext(user_id="test_user")
    
    # Context should not be expired initially
    assert not context.is_expired()
    
    # Set timestamp to past (beyond timeout)
    context.timestamp = datetime.utcnow() - timedelta(seconds=400)
    
    # Context should now be expired
    assert context.is_expired()


def test_context_reset():
    """Test that context reset clears all data."""
    context = CommandContext(user_id="test_user")
    
    # Set some context data
    context.last_track = "Bohemian Rhapsody"
    context.last_artist = "Queen"
    context.last_album = "A Night at the Opera"
    context.conversation_history = ["play bohemian rhapsody"]
    
    # Reset context
    context.reset()
    
    # All data should be cleared
    assert context.last_track is None
    assert context.last_artist is None
    assert context.last_album is None
    assert len(context.conversation_history) == 0


def test_follow_up_command_play_another_by_artist():
    """Test parsing 'play another one by them' with context."""
    parser = CommandParser()
    
    # Create context with previous artist
    context = CommandContext(user_id="test_user")
    context.last_artist = "The Beatles"
    context.last_track = "Hey Jude"
    
    # Parse follow-up command
    intent = parser.parse_command("play another one by them", context)
    
    # Should recognize as play_another_by_artist intent
    assert intent.intent == "play_another_by_artist"
    
    # Should have artist from context
    assert intent.parameters.get("artist") == "The Beatles"
    assert intent.parameters.get("_context_resolved") is True


def test_follow_up_command_without_context():
    """Test follow-up command without context should need clarification."""
    parser = CommandParser()
    
    # Create empty context
    context = CommandContext(user_id="test_user")
    
    # Parse follow-up command
    intent = parser.parse_command("play another one by them", context)
    
    # Should recognize intent but need clarification
    assert intent.intent == "play_another_by_artist"
    assert intent.parameters.get("_needs_clarification") is True


def test_play_more_like_this():
    """Test 'play more like this' with context."""
    parser = CommandParser()
    
    # Create context with previous track
    context = CommandContext(user_id="test_user")
    context.last_track = "Stairway to Heaven"
    context.last_artist = "Led Zeppelin"
    
    # Parse follow-up command
    intent = parser.parse_command("play more like this", context)
    
    # Should recognize as play_more_like_this intent
    assert intent.intent == "play_more_like_this"
    
    # Should have reference track and artist from context
    assert intent.parameters.get("reference_track") == "Stairway to Heaven"
    assert intent.parameters.get("reference_artist") == "Led Zeppelin"
    assert intent.parameters.get("_context_resolved") is True


def test_play_from_same_album():
    """Test 'play more from this album' with context."""
    parser = CommandParser()
    
    # Create context with previous album
    context = CommandContext(user_id="test_user")
    context.last_album = "Abbey Road"
    context.last_artist = "The Beatles"
    
    # Parse follow-up command
    intent = parser.parse_command("play more from this album", context)
    
    # Should recognize as play_from_same_album intent
    assert intent.intent == "play_from_same_album"
    
    # Should have album and artist from context
    assert intent.parameters.get("album") == "Abbey Road"
    assert intent.parameters.get("artist") == "The Beatles"
    assert intent.parameters.get("_context_resolved") is True


def test_context_update_with_result():
    """Test that context is updated with command result data."""
    agent = VoiceAgentService()
    
    # Create a command intent
    from app.services.command_parser import CommandIntent
    intent = CommandIntent(
        intent="play_track",
        parameters={"track": "Bohemian Rhapsody"},
        confidence=0.9,
        requires_clarification=False,
        raw_text="play bohemian rhapsody"
    )
    
    # Create a successful result
    result = CommandResult(
        success=True,
        message="Now playing",
        data={
            "track_name": "Bohemian Rhapsody",
            "artist_name": "Queen",
            "album_name": "A Night at the Opera"
        }
    )
    
    # Update context
    user_id = "test_user"
    agent.update_context(user_id, intent, result)
    
    # Check context was updated
    context = agent.get_or_create_context(user_id)
    assert context.last_track == "Bohemian Rhapsody"
    assert context.last_artist == "Queen"
    assert context.last_album == "A Night at the Opera"
    assert len(context.conversation_history) == 1


def test_context_timeout_resets_on_new_command():
    """Test that expired context is reset when getting context."""
    agent = VoiceAgentService()
    user_id = "test_user"
    
    # Create context with data
    context = agent.get_or_create_context(user_id)
    context.last_artist = "Queen"
    context.last_track = "Bohemian Rhapsody"
    
    # Set timestamp to expired
    context.timestamp = datetime.utcnow() - timedelta(seconds=400)
    
    # Get context again (should reset)
    context = agent.get_or_create_context(user_id)
    
    # Context should be reset
    assert context.last_artist is None
    assert context.last_track is None


def test_implicit_artist_context():
    """Test that track commands without artist use context."""
    parser = CommandParser()
    
    # Create context with previous artist
    context = CommandContext(user_id="test_user")
    context.last_artist = "The Beatles"
    
    # Parse command without artist
    intent = parser.parse_command("play yellow submarine", context)
    
    # Should be play_track intent
    assert intent.intent == "play_track"
    
    # Should have track and artist from context
    assert intent.parameters.get("track") == "yellow submarine"
    assert intent.parameters.get("artist") == "The Beatles"
    assert intent.parameters.get("_context_resolved") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
