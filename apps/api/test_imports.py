#!/usr/bin/env python3
"""Test script to verify imports work correctly."""

import sys
import traceback

def test_imports():
    """Test all imports for the WebSocket endpoint."""
    print("Testing imports...")
    
    try:
        print("1. Testing database imports...")
        from app.database import SessionLocal
        from app.models.integration import Integration
        print("   ✓ Database imports successful")
        
        print("2. Testing service imports...")
        from app.services.auth import supabase_auth_service
        from app.services.soniox import soniox_service
        from app.services.spotify import spotify_service
        print("   ✓ Basic service imports successful")
        
        print("3. Testing spotify_controller imports...")
        from app.services.spotify_controller import (
            NoActiveDeviceError,
            SearchNoResultsError,
            SpotifyAPIError,
            PremiumRequiredError,
            spotify_controller,
        )
        print("   ✓ Spotify controller imports successful")
        
        print("4. Testing voice_agent imports...")
        from app.services.voice_agent import voice_agent_service
        print("   ✓ Voice agent imports successful")
        
        print("5. Testing router imports...")
        from app.routers import speech_to_text_stream
        print("   ✓ Router imports successful")
        
        print("\n✅ All imports successful!")
        return True
        
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
